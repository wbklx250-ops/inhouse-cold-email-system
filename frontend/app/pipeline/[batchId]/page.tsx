"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const STEP_NAMES: Record<number, string> = {
  1: "Create Cloudflare Zones",
  2: "Update Nameservers",
  3: "Verify NS Propagation",
  4: "Create DNS Records",
  5: "First Login",
  6: "M365 Domain Setup",
  7: "Create Mailboxes",
  8: "Enable SMTP Auth",
  9: "Export Credentials",
  10: "Upload to Sequencer",
};

interface PipelineStatus {
  status: string;
  batch_id: string;
  batch_name: string;
  current_step: number;
  current_step_name: string;
  message: string;
  total_domains: number;
  total_tenants: number;
  nameserver_groups?: Array<{ nameservers: string[]; domains: string[]; count: number }>;
  steps: Record<string, { status: string; completed: number; failed: number; total: number }>;
  errors: Array<{ step: number; error: string }>;
  activity_log: Array<{ step: number; step_name: string; item_name: string; status: string; message: string; timestamp: string }>;
  completed_at?: string;
}

interface LogEntry {
  step: number;
  step_name: string;
  item_type: string;
  item_name: string;
  status: string;
  message: string;
  error: string | null;
  timestamp: string;
}

export default function PipelineDashboard() {
  const params = useParams();
  const batchId = params.batchId as string;

  const [pipelineStatus, setPipelineStatus] = useState<PipelineStatus | null>(null);
  const [activityLog, setActivityLog] = useState<LogEntry[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/pipeline/${batchId}/status`);
      if (res.ok) {
        const data = await res.json();
        setPipelineStatus(data);
      }
    } catch {
      console.error("Failed to fetch status");
    }
    setIsLoading(false);
  }, [batchId]);

  const fetchActivityLog = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/pipeline/${batchId}/activity-log?limit=20`);
      if (res.ok) {
        const data = await res.json();
        setActivityLog(data.logs || []);
      }
    } catch {
      console.error("Failed to fetch activity log");
    }
  }, [batchId]);

  // Poll for status every 3 seconds while running
  useEffect(() => {
    fetchStatus();
    fetchActivityLog();

    const interval = setInterval(() => {
      fetchStatus();
      fetchActivityLog();
    }, 3000);

    return () => clearInterval(interval);
  }, [fetchStatus, fetchActivityLog]);

  const confirmNameservers = async () => {
    await fetch(`${API_BASE}/api/v1/pipeline/${batchId}/confirm-nameservers`, { method: "POST" });
    fetchStatus();
  };

  const pausePipeline = async () => {
    await fetch(`${API_BASE}/api/v1/pipeline/${batchId}/pause`, { method: "POST" });
    fetchStatus();
  };

  const resumePipeline = async () => {
    await fetch(`${API_BASE}/api/v1/pipeline/${batchId}/resume`, { method: "POST" });
    fetchStatus();
  };

  const retryFailed = async () => {
    await fetch(`${API_BASE}/api/v1/pipeline/${batchId}/retry-failed`, { method: "POST" });
    fetchStatus();
  };

  const downloadCredentials = () => {
    window.open(`${API_BASE}/api/v1/pipeline/${batchId}/credentials-export`, "_blank");
  };

  if (isLoading) {
    return <div className="max-w-4xl mx-auto py-12 text-center text-gray-500">Loading pipeline...</div>;
  }

  if (!pipelineStatus) {
    return <div className="max-w-4xl mx-auto py-12 text-center text-red-500">Pipeline not found</div>;
  }

  const isRunning = pipelineStatus.status === "running";
  const isPaused = pipelineStatus.status === "paused";
  const isComplete = pipelineStatus.status === "completed";
  const isError = pipelineStatus.status === "error";
  const waitingForNS = pipelineStatus.current_step === 2 && isPaused;
  const failedSteps = pipelineStatus.errors || [];

  return (
    <div className="max-w-4xl mx-auto py-8 px-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{pipelineStatus.batch_name}</h1>
          <p className="text-sm text-gray-500">
            {pipelineStatus.total_domains} domains · {pipelineStatus.total_tenants} tenants
          </p>
        </div>
        <div className="flex gap-2">
          {isRunning && (
            <button onClick={pausePipeline} className="px-4 py-2 text-sm rounded-lg border border-gray-300 hover:bg-gray-50">
              Pause
            </button>
          )}
          {isPaused && !waitingForNS && (
            <button onClick={resumePipeline} className="px-4 py-2 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700">
              Resume
            </button>
          )}
          {(isComplete || isError) && (
            <button onClick={retryFailed} className="px-4 py-2 text-sm rounded-lg bg-orange-500 text-white hover:bg-orange-600">
              Retry Failed
            </button>
          )}
          {isComplete && (
            <button onClick={downloadCredentials} className="px-4 py-2 text-sm rounded-lg bg-green-600 text-white hover:bg-green-700">
              Download Credentials
            </button>
          )}
        </div>
      </div>

      {/* Overall Status Banner */}
      <div className={`rounded-lg p-4 mb-6 text-sm font-medium ${
        isComplete ? "bg-green-50 text-green-800 border border-green-200" :
        isError ? "bg-red-50 text-red-800 border border-red-200" :
        isPaused ? "bg-yellow-50 text-yellow-800 border border-yellow-200" :
        "bg-blue-50 text-blue-800 border border-blue-200"
      }`}>
        {pipelineStatus.message}
      </div>

      {/* NS Update Prompt (only shows at Step 2) */}
      {waitingForNS && pipelineStatus.nameserver_groups && (
        <div className="rounded-lg border-2 border-yellow-400 bg-yellow-50 p-6 mb-6">
          <h2 className="text-lg font-bold text-yellow-900 mb-3">⏸ Update Nameservers at Porkbun</h2>
          <p className="text-sm text-yellow-800 mb-4">
            Update the nameservers for all domains below, then click confirm.
          </p>

          {pipelineStatus.nameserver_groups.map((group, i) => (
            <div key={i} className="bg-white rounded-lg p-4 mb-3 border border-yellow-200">
              <p className="text-xs text-gray-500 mb-1">{group.count} domain(s):</p>
              <div className="flex gap-2 mb-2">
                {group.nameservers.map((ns) => (
                  <code
                    key={ns}
                    className="bg-gray-100 px-3 py-1 rounded text-sm font-mono cursor-pointer hover:bg-gray-200"
                    onClick={() => navigator.clipboard.writeText(ns)}
                    title="Click to copy"
                  >
                    {ns}
                  </code>
                ))}
              </div>
              <p className="text-xs text-gray-400">
                {group.domains.slice(0, 5).join(", ")}
                {group.domains.length > 5 && ` + ${group.domains.length - 5} more`}
              </p>
            </div>
          ))}

          <button
            onClick={confirmNameservers}
            className="mt-4 w-full rounded-lg bg-yellow-600 py-3 text-sm font-semibold text-white hover:bg-yellow-700"
          >
            ✓ I&apos;ve Updated All Nameservers — Continue
          </button>
        </div>
      )}

      {/* Step Progress */}
      <div className="space-y-2 mb-8">
        {Object.entries(STEP_NAMES).map(([stepNum, stepName]) => {
          const step = Number(stepNum);
          const stepData = pipelineStatus.steps?.[stepNum];
          const isCurrent = pipelineStatus.current_step === step;
          const isStepComplete = stepData?.status === "completed";
          const isStepError = stepData?.status === "error";
          const isStepRunning = stepData?.status === "running";
          const isStepSkipped = stepData?.status === "skipped";

          return (
            <div
              key={step}
              className={`flex items-center justify-between rounded-lg px-4 py-3 text-sm ${
                isStepComplete ? "bg-green-50 border border-green-200" :
                isStepError ? "bg-red-50 border border-red-200" :
                isStepRunning || isCurrent ? "bg-blue-50 border border-blue-300" :
                isStepSkipped ? "bg-gray-50 border border-gray-200" :
                "bg-gray-50 border border-gray-100"
              }`}
            >
              <div className="flex items-center gap-3">
                <span className="text-base">
                  {isStepComplete ? "✅" :
                   isStepError ? "❌" :
                   isStepRunning || isCurrent ? "🔄" :
                   isStepSkipped ? "⏭️" :
                   "⬜"}
                </span>
                <span className={isCurrent ? "font-semibold" : ""}>
                  Step {step}: {stepName}
                </span>
              </div>
              {stepData && (stepData.completed > 0 || stepData.failed > 0) && (
                <span className="text-xs text-gray-500">
                  {stepData.completed} done
                  {stepData.failed > 0 && <span className="text-red-500"> · {stepData.failed} failed</span>}
                </span>
              )}
            </div>
          );
        })}
      </div>

      {/* Errors Panel */}
      {failedSteps.length > 0 && (
        <div className="mb-8">
          <h2 className="text-lg font-semibold text-gray-900 mb-3">Errors</h2>
          <div className="space-y-2">
            {failedSteps.map((err, i) => (
              <div key={i} className="rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-800">
                <span className="font-medium">Step {err.step}:</span> {err.error}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Activity Log */}
      <div>
        <h2 className="text-lg font-semibold text-gray-900 mb-3">Recent Activity</h2>
        <div className="border border-gray-200 rounded-lg divide-y divide-gray-100 max-h-96 overflow-y-auto">
          {activityLog.length === 0 ? (
            <p className="p-4 text-sm text-gray-400">No activity yet...</p>
          ) : (
            activityLog.map((entry, i) => (
              <div key={i} className="flex items-center justify-between px-4 py-2.5 text-sm">
                <div className="flex items-center gap-2">
                  <span className={`inline-block w-2 h-2 rounded-full ${
                    entry.status === "completed" ? "bg-green-500" :
                    entry.status === "failed" ? "bg-red-500" :
                    entry.status === "started" ? "bg-blue-500" :
                    "bg-gray-400"
                  }`} />
                  <span className="text-gray-600">{entry.step_name}</span>
                  {entry.item_name && (
                    <span className="font-medium text-gray-900">{entry.item_name}</span>
                  )}
                  {entry.message && (
                    <span className="text-gray-400">— {entry.message}</span>
                  )}
                </div>
                <span className="text-xs text-gray-400 whitespace-nowrap">
                  {new Date(entry.timestamp).toLocaleTimeString()}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
