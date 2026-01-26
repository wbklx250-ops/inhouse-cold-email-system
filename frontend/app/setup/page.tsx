"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";

interface Batch {
  id: string;
  name: string;
  description: string | null;
  current_step: number;
  status: string;
  redirect_url: string | null;
  created_at: string;
  domains_count: number;
  tenants_count: number;
  mailboxes_count: number;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const stepNames: Record<number, string> = {
  1: "Import Domains",
  2: "Create Zones",
  3: "Verify NS",
  4: "Import Tenants",
  5: "Email Setup",
  6: "Mailboxes",
  7: "Complete",
};

export default function SetupBatchList() {
  const router = useRouter();
  const [batches, setBatches] = useState<Batch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [newBatchName, setNewBatchName] = useState("");
  const [newBatchDesc, setNewBatchDesc] = useState("");
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    loadBatches();
  }, []);

  const loadBatches = async () => {
    try {
      setLoading(true);
      const res = await fetch(`${API_BASE}/api/v1/wizard/batches`);
      if (!res.ok) throw new Error("Failed to load batches");
      const data = await res.json();
      setBatches(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  };

  const createBatch = async () => {
    if (!newBatchName.trim()) return;
    setCreating(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/wizard/batches`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newBatchName, description: newBatchDesc }),
      });
      if (!res.ok) throw new Error("Failed to create batch");
      const batch = await res.json();
      router.push(`/setup/${batch.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create");
    } finally {
      setCreating(false);
    }
  };

  const pauseBatch = async (id: string) => {
    await fetch(`${API_BASE}/api/v1/wizard/batches/${id}/pause`, { method: "PATCH" });
    loadBatches();
  };

  const resumeBatch = async (id: string) => {
    await fetch(`${API_BASE}/api/v1/wizard/batches/${id}/resume`, { method: "PATCH" });
    loadBatches();
  };

  const deleteBatch = async (id: string, name: string) => {
    if (!confirm(`Delete batch "${name}"? This cannot be undone.`)) return;
    await fetch(`${API_BASE}/api/v1/wizard/batches/${id}`, { method: "DELETE" });
    loadBatches();
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="bg-white shadow">
        <div className="max-w-6xl mx-auto px-4 py-6">
          <h1 className="text-2xl font-bold text-gray-900">Setup Batches</h1>
          <p className="text-gray-600 mt-1">
            Manage your cold email setup sessions. Each batch is an independent setup workflow.
          </p>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-4 py-8">
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6">
            <p className="text-red-800">{error}</p>
          </div>
        )}

        {/* Create New Batch */}
        {!showCreate ? (
          <button
            onClick={() => setShowCreate(true)}
            className="mb-8 px-6 py-3 bg-blue-600 text-white font-bold rounded-lg hover:bg-blue-700 flex items-center gap-2"
          >
            <span className="text-xl">+</span> New Setup Batch
          </button>
        ) : (
          <div className="mb-8 bg-white rounded-lg shadow p-6">
            <h2 className="text-lg font-bold mb-4">Create New Batch</h2>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Batch Name *
                </label>
                <input
                  type="text"
                  value={newBatchName}
                  onChange={(e) => setNewBatchName(e.target.value)}
                  placeholder="e.g., January 2026 Setup, Client ABC Domains"
                  className="w-full px-4 py-2 border rounded-lg"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Description (optional)
                </label>
                <input
                  type="text"
                  value={newBatchDesc}
                  onChange={(e) => setNewBatchDesc(e.target.value)}
                  placeholder="Notes about this batch..."
                  className="w-full px-4 py-2 border rounded-lg"
                />
              </div>
              <div className="flex gap-3">
                <button
                  onClick={createBatch}
                  disabled={!newBatchName.trim() || creating}
                  className="px-6 py-2 bg-blue-600 text-white font-bold rounded-lg hover:bg-blue-700 disabled:bg-gray-300"
                >
                  {creating ? "Creating..." : "Create & Start Setup"}
                </button>
                <button
                  onClick={() => {
                    setShowCreate(false);
                    setNewBatchName("");
                    setNewBatchDesc("");
                  }}
                  className="px-6 py-2 border border-gray-300 rounded-lg hover:bg-gray-50"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Batch List */}
        {batches.length === 0 ? (
          <div className="text-center py-12 bg-white rounded-lg shadow">
            <div className="text-5xl mb-4">📦</div>
            <h2 className="text-xl font-bold text-gray-900">No batches yet</h2>
            <p className="text-gray-600 mt-2">
              Create your first batch to start setting up cold email infrastructure.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {batches.map((batch) => (
              <BatchCard
                key={batch.id}
                batch={batch}
                onOpen={() => router.push(`/setup/${batch.id}`)}
                onPause={() => pauseBatch(batch.id)}
                onResume={() => resumeBatch(batch.id)}
                onDelete={() => deleteBatch(batch.id, batch.name)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function BatchCard({
  batch,
  onOpen,
  onPause,
  onResume,
  onDelete,
}: {
  batch: Batch;
  onOpen: () => void;
  onPause: () => void;
  onResume: () => void;
  onDelete: () => void;
}) {
  const statusColors: Record<string, string> = {
    active: "bg-green-100 text-green-800",
    paused: "bg-yellow-100 text-yellow-800",
    completed: "bg-blue-100 text-blue-800",
  };

  const stepProgress = Math.min((batch.current_step / 7) * 100, 100);

  return (
    <div className="bg-white rounded-lg shadow p-6 hover:shadow-lg transition-shadow">
      <div className="flex justify-between items-start">
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <h3 className="text-lg font-bold text-gray-900">{batch.name}</h3>
            <span
              className={`px-2 py-1 rounded-full text-xs font-medium ${
                statusColors[batch.status] || "bg-gray-100"
              }`}
            >
              {batch.status}
            </span>
          </div>
          {batch.description && (
            <p className="text-gray-600 text-sm mt-1">{batch.description}</p>
          )}

          {/* Progress Bar */}
          <div className="mt-4">
            <div className="flex justify-between text-sm text-gray-600 mb-1">
              <span>Step {batch.current_step}: {stepNames[batch.current_step]}</span>
              <span>{Math.round(stepProgress)}%</span>
            </div>
            <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
              <div
                className={`h-full transition-all ${
                  batch.status === "completed" ? "bg-green-500" : "bg-blue-500"
                }`}
                style={{ width: `${stepProgress}%` }}
              />
            </div>
          </div>

          {/* Stats */}
          <div className="flex gap-6 mt-4 text-sm">
            <div>
              <span className="text-gray-500">Domains:</span>{" "}
              <span className="font-medium">{batch.domains_count}</span>
            </div>
            <div>
              <span className="text-gray-500">Tenants:</span>{" "}
              <span className="font-medium">{batch.tenants_count}</span>
            </div>
            <div>
              <span className="text-gray-500">Mailboxes:</span>{" "}
              <span className="font-medium">{batch.mailboxes_count}</span>
            </div>
          </div>

          <p className="text-xs text-gray-400 mt-3">
            Created: {new Date(batch.created_at).toLocaleDateString()}
          </p>
        </div>

        {/* Actions */}
        <div className="flex flex-col gap-2 ml-4">
          <button
            onClick={onOpen}
            className="px-4 py-2 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700"
          >
            {batch.status === "completed" ? "View" : "Continue"}
          </button>
          {batch.status === "active" && (
            <button
              onClick={onPause}
              className="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 text-sm"
            >
              Pause
            </button>
          )}
          {batch.status === "paused" && (
            <button
              onClick={onResume}
              className="px-4 py-2 border border-green-300 text-green-700 rounded-lg hover:bg-green-50 text-sm"
            >
              Resume
            </button>
          )}
          <button
            onClick={onDelete}
            className="px-4 py-2 text-red-600 hover:bg-red-50 rounded-lg text-sm"
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}