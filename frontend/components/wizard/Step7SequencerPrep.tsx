"use client";

import React, { useState, useEffect, useCallback } from "react";

interface TenantStep7Status {
  id: string;
  domain: string;
  step7_complete: boolean;
  smtp_auth_enabled: boolean;
  error: string | null;
  completed_at: string | null;
}

interface Step7Status {
  batch_complete: boolean;
  eligible: number;
  complete: number;
  failed: number;
  pending: number;
  tenants: TenantStep7Status[];
}

interface Props {
  batchId: string;
  onComplete?: () => void;
}

export default function Step7SequencerPrep({ batchId, onComplete }: Props) {
  const [status, setStatus] = useState<Step7Status | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(
        `${API_BASE}/api/v1/wizard/batches/${batchId}/step7/status`
      );
      if (res.ok) {
        const data: Step7Status = await res.json();
        setStatus(data);

        // Auto-stop polling when all done
        if (data.eligible > 0 && data.complete === data.eligible) {
          setIsRunning(false);
        }

        // Notify parent if batch is fully complete
        if (data.batch_complete) {
          onComplete?.();
        }
      }
    } catch (err) {
      console.error("Failed to fetch Step 7 status:", err);
    } finally {
      setLoading(false);
    }
  }, [batchId, API_BASE, onComplete]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  // Poll every 5 seconds while running
  useEffect(() => {
    if (!isRunning) return;
    const interval = setInterval(fetchStatus, 5000);
    return () => clearInterval(interval);
  }, [isRunning, fetchStatus]);

  const startStep7 = async () => {
    setError(null);
    setIsRunning(true);
    try {
      const res = await fetch(
        `${API_BASE}/api/v1/wizard/batches/${batchId}/step7/start`,
        { method: "POST" }
      );
      const data = await res.json();
      if (!data.success) {
        setError(data.error || "Failed to start Step 7");
        setIsRunning(false);
      }
    } catch (err) {
      setError("Network error starting Step 7");
      setIsRunning(false);
    }
  };

  const retryFailed = async () => {
    setError(null);
    setIsRunning(true);
    try {
      const res = await fetch(
        `${API_BASE}/api/v1/wizard/batches/${batchId}/step7/retry-failed`,
        { method: "POST" }
      );
      const data = await res.json();
      if (!data.success) {
        setError(data.error || "Failed to retry");
        setIsRunning(false);
      }
    } catch (err) {
      setError("Network error retrying");
      setIsRunning(false);
    }
  };

  if (loading) {
    return <div className="p-6 text-gray-500">Loading Step 7 status...</div>;
  }

  const allComplete =
    status && status.eligible > 0 && status.complete === status.eligible;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-xl font-semibold text-gray-900">
          Step 7: Enable SMTP Auth for Sequencer Upload
        </h2>
        <p className="mt-1 text-sm text-gray-500">
          Enables SMTP Authentication at the organization level in each tenant
          so mailboxes can be connected to{" "}
          <strong>PlusVibe</strong>, <strong>Instantly</strong>, or other
          email sequencers.
        </p>
      </div>

      {/* Info banner */}
      <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-700">
        <p className="font-medium">What this does:</p>
        <p className="mt-1">
          Logs into each tenant's Exchange Admin Center and unchecks "Turn off
          SMTP AUTH protocol" under Settings &rarr; Mail flow. This is one
          toggle per tenant and takes about 30 seconds each.
        </p>
        <p className="mt-2 text-blue-600">
          <strong>Note:</strong> Microsoft may take up to 1 hour to fully sync
          this change. Sequencer connections may not work immediately.
        </p>
      </div>

      {/* Status grid */}
      {status && (
        <div className="grid grid-cols-4 gap-4">
          <div className="rounded-lg border p-4 text-center">
            <p className="text-2xl font-bold text-gray-900">
              {status.eligible}
            </p>
            <p className="text-sm text-gray-500">Eligible</p>
          </div>
          <div className="rounded-lg border p-4 text-center">
            <p className="text-2xl font-bold text-green-600">
              {status.complete}
            </p>
            <p className="text-sm text-gray-500">Complete</p>
          </div>
          <div className="rounded-lg border p-4 text-center">
            <p className="text-2xl font-bold text-yellow-600">
              {status.pending}
            </p>
            <p className="text-sm text-gray-500">Pending</p>
          </div>
          <div className="rounded-lg border p-4 text-center">
            <p className="text-2xl font-bold text-red-600">
              {status.failed}
            </p>
            <p className="text-sm text-gray-500">Failed</p>
          </div>
        </div>
      )}

      {/* Progress bar */}
      {status && status.eligible > 0 && (
        <div className="w-full bg-gray-200 rounded-full h-3">
          <div
            className={`h-3 rounded-full transition-all duration-500 ${
              allComplete ? "bg-green-500" : "bg-blue-500"
            }`}
            style={{
              width: `${Math.round(
                (status.complete / status.eligible) * 100
              )}%`,
            }}
          />
        </div>
      )}

      {/* Action buttons */}
      <div className="flex gap-3">
        {!allComplete && (
          <button
            onClick={startStep7}
            disabled={isRunning || !status || status.eligible === 0}
            className={`px-6 py-2.5 rounded-lg font-medium text-white transition-colors ${
              isRunning || !status || status.eligible === 0
                ? "bg-gray-400 cursor-not-allowed"
                : "bg-blue-600 hover:bg-blue-700"
            }`}
          >
            {isRunning ? (
              <span className="flex items-center gap-2">
                <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                    fill="none"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                  />
                </svg>
                Enabling SMTP Auth...
              </span>
            ) : status?.complete && status.complete > 0 ? (
              "Continue Processing"
            ) : (
              "Enable SMTP Auth"
            )}
          </button>
        )}

        {status && status.failed > 0 && (
          <button
            onClick={retryFailed}
            disabled={isRunning}
            className={`px-6 py-2.5 rounded-lg font-medium transition-colors ${
              isRunning
                ? "bg-gray-200 text-gray-400 cursor-not-allowed"
                : "bg-orange-100 text-orange-700 hover:bg-orange-200"
            }`}
          >
            Retry {status.failed} Failed
          </button>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Success — Batch Complete */}
      {allComplete && (
        <div className="rounded-lg border border-green-200 bg-green-50 p-4">
          <p className="text-lg font-semibold text-green-700">
            Setup Complete!
          </p>
          <p className="mt-1 text-sm text-green-600">
            All tenants have SMTP Auth enabled. Your mailboxes are ready
            to upload to PlusVibe, Instantly, or any other sequencer.
          </p>
          <div className="mt-3 rounded border border-green-300 bg-white p-3 text-xs font-mono text-gray-700 space-y-1">
            <p><strong>SMTP Host:</strong> smtp.office365.com &nbsp;|&nbsp; <strong>Port:</strong> 587</p>
            <p><strong>IMAP Host:</strong> outlook.office365.com &nbsp;|&nbsp; <strong>Port:</strong> 993</p>
            <p><strong>Encryption:</strong> TLS / STARTTLS</p>
            <p><strong>Username:</strong> mailbox email address</p>
            <p><strong>Password:</strong> password set in Step 6</p>
          </div>
          <p className="mt-2 text-xs text-green-500">
            Allow up to 1 hour for Microsoft to fully propagate SMTP Auth
            changes before testing connections.
          </p>
        </div>
      )}

      {/* Tenant table */}
      {status && status.tenants.length > 0 && (
        <div className="rounded-lg border overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Domain
                </th>
                <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">
                  SMTP Auth
                </th>
                <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">
                  Status
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Error
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {status.tenants.map((t) => (
                <tr key={t.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm font-medium text-gray-900">
                    {t.domain}
                  </td>
                  <td className="px-4 py-3 text-center">
                    {t.smtp_auth_enabled ? (
                      <span className="text-green-500 text-lg">&#10003;</span>
                    ) : (
                      <span className="text-gray-300">&mdash;</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-center">
                    {t.step7_complete ? (
                      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                        Done
                      </span>
                    ) : t.error ? (
                      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800">
                        Failed
                      </span>
                    ) : (
                      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600">
                        Pending
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm text-red-500 max-w-xs truncate">
                    {t.error || "\u2014"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
