"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Batch {
  id: string;
  name: string;
  description: string | null;
  current_step: number;
  status: string; // "active", "in_progress", "paused", "completed"
  created_at: string;
  domains_count: number;
  tenants_count: number;
  mailboxes_count: number;
  uploaded_to_sequencer: boolean;
  uploaded_at: string | null;
}

// For each batch, also try to fetch pipeline status
interface PipelineInfo {
  pipeline_status?: string; // "running", "paused", "completed", "error", "not_started"
  pipeline_step?: number;
  pipeline_step_name?: string;
  total_domains?: number;
  total_tenants?: number;
}

export default function PipelineListPage() {
  const router = useRouter();
  const [batches, setBatches] = useState<(Batch & PipelineInfo)[]>([]);
  const [loading, setLoading] = useState(true);

  const loadBatches = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/wizard/batches`);
      if (!res.ok) throw new Error("Failed to load");
      const data: Batch[] = await res.json();

      // For each batch, try to get pipeline status
      const enriched = await Promise.all(
        data.map(async (batch) => {
          try {
            const statusRes = await fetch(`${API_BASE}/api/v1/pipeline/${batch.id}/status`);
            if (statusRes.ok) {
              const statusData = await statusRes.json();
              return {
                ...batch,
                pipeline_status: statusData.status,
                pipeline_step: statusData.current_step,
                pipeline_step_name: statusData.current_step_name,
                total_domains: statusData.total_domains,
                total_tenants: statusData.total_tenants,
              };
            }
          } catch {}
          return batch;
        })
      );

      setBatches(enriched);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadBatches();
    const interval = setInterval(loadBatches, 10000);
    return () => clearInterval(interval);
  }, []);

  const deleteBatch = async (id: string, name: string) => {
    if (!confirm(`Delete batch "${name}"? This cannot be undone.`)) return;
    await fetch(`${API_BASE}/api/v1/wizard/batches/${id}`, { method: "DELETE" });
    loadBatches();
  };

  // Status badge helper
  const getStatusBadge = (batch: Batch & PipelineInfo) => {
    const ps = batch.pipeline_status;
    if (ps === "completed") return { text: "Completed", color: "bg-green-100 text-green-800" };
    if (ps === "running") return { text: "Running", color: "bg-blue-100 text-blue-800" };
    if (ps === "paused") return { text: "Paused", color: "bg-yellow-100 text-yellow-800" };
    if (ps === "error") return { text: "Error", color: "bg-red-100 text-red-800" };
    if (batch.status === "completed") return { text: "Completed", color: "bg-green-100 text-green-800" };
    if (batch.status === "paused") return { text: "Paused", color: "bg-yellow-100 text-yellow-800" };
    return { text: "Active", color: "bg-gray-100 text-gray-800" };
  };

  // Step display helper
  const getStepInfo = (batch: Batch & PipelineInfo): string => {
    if (batch.pipeline_step && batch.pipeline_step_name) {
      return `Step ${batch.pipeline_step}/10: ${batch.pipeline_step_name}`;
    }
    // Fallback to wizard step
    const wizardSteps: Record<number, string> = {
      1: "Import Domains", 2: "Create Zones", 3: "Verify NS",
      4: "Import Tenants", 5: "Email Setup", 6: "Mailboxes", 7: "Complete",
    };
    return `Step ${batch.current_step}/7: ${wizardSteps[batch.current_step] || "Unknown"}`;
  };

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto py-12 text-center text-gray-500">
        Loading batches...
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto py-8 px-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Batches</h1>
          <p className="text-sm text-gray-500">{batches.length} batch{batches.length !== 1 ? "es" : ""}</p>
        </div>
        <button
          onClick={() => router.push("/pipeline/new")}
          className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 transition-colors"
        >
          🚀 New Batch
        </button>
      </div>

      {/* Empty state */}
      {batches.length === 0 && (
        <div className="text-center py-16 bg-gray-50 rounded-xl border-2 border-dashed border-gray-200">
          <p className="text-xl mb-2">📭</p>
          <p className="text-gray-600 font-medium">No batches yet</p>
          <p className="text-sm text-gray-400 mt-1">Create your first batch to get started</p>
          <button
            onClick={() => router.push("/pipeline/new")}
            className="mt-4 inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
          >
            🚀 New Batch
          </button>
        </div>
      )}

      {/* Batch list */}
      <div className="space-y-3">
        {batches.map((batch) => {
          const badge = getStatusBadge(batch);
          const stepInfo = getStepInfo(batch);
          const isRunning = batch.pipeline_status === "running";

          return (
            <div
              key={batch.id}
              onClick={() => router.push(`/pipeline/${batch.id}`)}
              className={`bg-white rounded-lg border p-4 cursor-pointer hover:border-blue-300 hover:shadow-sm transition-all ${
                isRunning ? "border-blue-200 ring-1 ring-blue-100" : "border-gray-200"
              }`}
            >
              <div className="flex items-center justify-between">
                {/* Left: name + status */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <h3 className="font-semibold text-gray-900 truncate">{batch.name}</h3>
                    <span className={`inline-flex px-2 py-0.5 text-xs font-medium rounded-full ${badge.color}`}>
                      {badge.text}
                    </span>
                    {isRunning && (
                      <span className="inline-flex items-center gap-1 text-xs text-blue-600">
                        <span className="animate-pulse">●</span> Live
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-gray-500">{stepInfo}</p>
                </div>

                {/* Right: counts + date */}
                <div className="flex items-center gap-6 text-sm text-gray-500 ml-4">
                  <div className="text-right">
                    <span className="font-medium text-gray-700">{batch.total_domains || batch.domains_count}</span> domains
                  </div>
                  <div className="text-right">
                    <span className="font-medium text-gray-700">{batch.total_tenants || batch.tenants_count}</span> tenants
                  </div>
                  <div className="text-right text-xs">
                    {new Date(batch.created_at).toLocaleDateString()}
                  </div>
                  {/* Delete button - stop propagation so click doesn't navigate */}
                  <button
                    onClick={(e) => { e.stopPropagation(); deleteBatch(batch.id, batch.name); }}
                    className="text-gray-400 hover:text-red-500 transition-colors"
                    title="Delete batch"
                  >
                    🗑️
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
