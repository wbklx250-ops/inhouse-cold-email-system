"use client";

import React, { useState, useEffect, useCallback } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ============================================================================
// Types
// ============================================================================

interface DashboardStats {
  total_mailboxes: number;
  total_ready: number;
  total_uploaded: number;
  total_pending: number;
  total_errored: number;
  total_not_ready: number;
  batches_with_pending: number;
}

interface BatchSummary {
  batch_id: string;
  batch_name: string;
  batch_status: string;
  total_mailboxes: number;
  ready: number;
  uploaded: number;
  pending: number;
  errored: number;
  not_ready: number;
  created_at: string;
}

interface MailboxItem {
  id: string;
  email: string;
  display_name: string;
  password: string | null;
  tenant_id: string;
  tenant_name: string | null;
  domain_name: string | null;
  batch_id: string | null;
  batch_name: string | null;
  status: string;
  setup_complete: boolean;
  uploaded_to_sequencer: boolean;
  uploaded_at: string | null;
  sequencer_name: string | null;
  upload_error: string | null;
}

interface MailboxListResponse {
  items: MailboxItem[];
  total: number;
  page: number;
  per_page: number;
  filter_ready: number;
  filter_uploaded: number;
  filter_pending: number;
}

// ============================================================================
// Stat Card Component
// ============================================================================

function StatCard({ label, value, color, icon }: { label: string; value: number; color: string; icon: string }) {
  const colorMap: Record<string, string> = {
    blue: "bg-blue-50 border-blue-200 text-blue-700",
    green: "bg-green-50 border-green-200 text-green-700",
    yellow: "bg-yellow-50 border-yellow-200 text-yellow-700",
    red: "bg-red-50 border-red-200 text-red-700",
    gray: "bg-gray-50 border-gray-200 text-gray-700",
    purple: "bg-purple-50 border-purple-200 text-purple-700",
  };
  return (
    <div className={`rounded-lg border p-4 ${colorMap[color] || colorMap.gray}`}>
      <div className="flex items-center justify-between">
        <span className="text-2xl">{icon}</span>
        <span className="text-2xl font-bold">{value}</span>
      </div>
      <p className="mt-1 text-sm font-medium">{label}</p>
    </div>
  );
}

// ============================================================================
// Progress Bar Component
// ============================================================================

function ProgressBar({ uploaded, pending, notReady, total }: { uploaded: number; pending: number; notReady: number; total: number }) {
  if (total === 0) return <div className="h-2 rounded-full bg-gray-200" />;
  const pctUploaded = (uploaded / total) * 100;
  const pctPending = (pending / total) * 100;
  return (
    <div className="h-2 rounded-full bg-gray-200 overflow-hidden flex">
      {pctUploaded > 0 && <div className="bg-green-500 h-full" style={{ width: `${pctUploaded}%` }} />}
      {pctPending > 0 && <div className="bg-yellow-500 h-full" style={{ width: `${pctPending}%` }} />}
    </div>
  );
}

// ============================================================================
// Main Page Component
// ============================================================================

export default function UploadManagerPage() {
  // State
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [batches, setBatches] = useState<BatchSummary[]>([]);
  const [mailboxes, setMailboxes] = useState<MailboxListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  // Filters
  const [uploadStatus, setUploadStatus] = useState<string>("pending");
  const [batchFilter, setBatchFilter] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [page, setPage] = useState(1);
  const perPage = 50;

  // Selection
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [selectAll, setSelectAll] = useState(false);

  // Export
  const [exportFormat, setExportFormat] = useState("instantly");

  // ============================================================================
  // Data Fetching
  // ============================================================================

  const fetchDashboard = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/upload/dashboard`);
      if (res.ok) setStats(await res.json());
    } catch (e) {
      console.error("Failed to fetch dashboard", e);
    }
  }, []);

  const fetchBatches = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/upload/batches`);
      if (res.ok) setBatches(await res.json());
    } catch (e) {
      console.error("Failed to fetch batches", e);
    }
  }, []);

  const fetchMailboxes = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("per_page", String(perPage));
      if (uploadStatus) params.set("upload_status", uploadStatus);
      if (batchFilter) params.set("batch_id", batchFilter);
      if (searchQuery) params.set("search", searchQuery);

      const res = await fetch(`${API_BASE}/api/v1/upload/mailboxes?${params}`);
      if (res.ok) {
        const data = await res.json();
        setMailboxes(data);
      }
    } catch (e) {
      console.error("Failed to fetch mailboxes", e);
    }
  }, [page, uploadStatus, batchFilter, searchQuery]);

  const refreshAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await Promise.all([fetchDashboard(), fetchBatches(), fetchMailboxes()]);
    } catch (e) {
      setError("Failed to load data");
    } finally {
      setLoading(false);
    }
  }, [fetchDashboard, fetchBatches, fetchMailboxes]);

  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

  // Reset page when filters change
  useEffect(() => {
    setPage(1);
    setSelectedIds(new Set());
    setSelectAll(false);
  }, [uploadStatus, batchFilter, searchQuery]);

  // ============================================================================
  // Actions
  // ============================================================================

  const handleMarkUploaded = async () => {
    if (selectedIds.size === 0) return;
    setActionMsg(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/upload/mark-uploaded`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mailbox_ids: Array.from(selectedIds), sequencer_name: exportFormat }),
      });
      if (res.ok) {
        const data = await res.json();
        setActionMsg(`Marked ${data.marked_count} mailboxes as uploaded`);
        setSelectedIds(new Set());
        setSelectAll(false);
        await refreshAll();
      }
    } catch (e) {
      setActionMsg("Error marking mailboxes");
    }
  };

  const handleMarkAllPending = async () => {
    setActionMsg(null);
    try {
      const params = new URLSearchParams({ sequencer_name: exportFormat });
      if (batchFilter) params.set("batch_id", batchFilter);
      const res = await fetch(`${API_BASE}/api/v1/upload/mark-all-pending?${params}`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setActionMsg(`Marked ${data.marked_count} pending mailboxes as uploaded`);
        await refreshAll();
      }
    } catch (e) {
      setActionMsg("Error marking all pending");
    }
  };

  const handleUnmark = async () => {
    if (selectedIds.size === 0) return;
    setActionMsg(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/upload/unmark`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mailbox_ids: Array.from(selectedIds) }),
      });
      if (res.ok) {
        const data = await res.json();
        setActionMsg(`Unmarked ${data.unmarked_count} mailboxes`);
        setSelectedIds(new Set());
        setSelectAll(false);
        await refreshAll();
      }
    } catch (e) {
      setActionMsg("Error unmarking mailboxes");
    }
  };

  const handleExportPending = async () => {
    const params = new URLSearchParams({ sequencer_format: exportFormat });
    if (batchFilter) params.set("batch_id", batchFilter);
    try {
      const res = await fetch(`${API_BASE}/api/v1/upload/export-pending?${params}`);
      if (!res.ok) {
        setActionMsg("No pending mailboxes to export");
        return;
      }
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const cd = res.headers.get("content-disposition");
      a.download = cd?.match(/filename="(.+)"/)?.[1] || "pending_export.csv";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
      setActionMsg("CSV exported");
    } catch (e) {
      setActionMsg("Export failed");
    }
  };

  const handleExportAll = async () => {
    const params = new URLSearchParams();
    if (batchFilter) params.set("batch_id", batchFilter);
    try {
      const res = await fetch(`${API_BASE}/api/v1/upload/export-all?${params}`);
      if (!res.ok) { setActionMsg("Export failed"); return; }
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const cd = res.headers.get("content-disposition");
      a.download = cd?.match(/filename="(.+)"/)?.[1] || "all_mailboxes.csv";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
      setActionMsg("Full audit CSV exported");
    } catch (e) {
      setActionMsg("Export failed");
    }
  };

  // ============================================================================
  // Selection helpers
  // ============================================================================

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectAll) {
      setSelectedIds(new Set());
      setSelectAll(false);
    } else {
      const ids = new Set(mailboxes?.items.map((m) => m.id) || []);
      setSelectedIds(ids);
      setSelectAll(true);
    }
  };

  const totalPages = mailboxes ? Math.ceil(mailboxes.total / perPage) : 0;

  // ============================================================================
  // Render
  // ============================================================================

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-3">
              <span className="text-4xl">📋</span>
              Upload Manager
            </h1>
            <p className="mt-2 text-gray-600">
              Cross-batch mailbox upload tracking and CSV export
            </p>
          </div>
          <button onClick={refreshAll} disabled={loading} className="px-4 py-2 bg-white border border-gray-300 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50">
            {loading ? "Loading..." : "🔄 Refresh"}
          </button>
        </div>

        {/* Error */}
        {error && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">{error}</div>
        )}

        {/* Action Message */}
        {actionMsg && (
          <div className="mb-6 p-4 bg-blue-50 border border-blue-200 rounded-lg text-blue-700 flex justify-between items-center">
            <span>{actionMsg}</span>
            <button onClick={() => setActionMsg(null)} className="text-blue-500 hover:text-blue-700 text-lg">✕</button>
          </div>
        )}

        {/* Dashboard Stats */}
        {stats && (
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4 mb-8">
            <StatCard label="Total" value={stats.total_mailboxes} color="blue" icon="📧" />
            <StatCard label="Ready" value={stats.total_ready} color="purple" icon="✅" />
            <StatCard label="Uploaded" value={stats.total_uploaded} color="green" icon="🚀" />
            <StatCard label="Pending" value={stats.total_pending} color="yellow" icon="⏳" />
            <StatCard label="Errored" value={stats.total_errored} color="red" icon="❌" />
            <StatCard label="Not Ready" value={stats.total_not_ready} color="gray" icon="🔧" />
            <StatCard label="Batches w/ Pending" value={stats.batches_with_pending} color="yellow" icon="📦" />
          </div>
        )}

        {/* Batch Summaries */}
        {batches.length > 0 && (
          <div className="bg-white rounded-lg border border-gray-200 p-6 mb-8">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Batch Summaries</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {batches.map((b) => (
                <div key={b.batch_id} className="border border-gray-200 rounded-lg p-4 hover:border-gray-300 transition-colors">
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="font-medium text-gray-900 truncate">{b.batch_name}</h3>
                    <span className={`text-xs px-2 py-0.5 rounded-full ${
                      b.pending > 0 ? "bg-yellow-100 text-yellow-700" : "bg-green-100 text-green-700"
                    }`}>
                      {b.pending > 0 ? `${b.pending} pending` : "All uploaded"}
                    </span>
                  </div>
                  <ProgressBar uploaded={b.uploaded} pending={b.pending} notReady={b.not_ready} total={b.total_mailboxes} />
                  <div className="mt-2 flex gap-3 text-xs text-gray-500">
                    <span>📧 {b.total_mailboxes}</span>
                    <span className="text-green-600">✅ {b.uploaded}</span>
                    <span className="text-yellow-600">⏳ {b.pending}</span>
                    <span className="text-gray-400">🔧 {b.not_ready}</span>
                  </div>
                  <button
                    onClick={() => { setBatchFilter(b.batch_id); setUploadStatus("pending"); }}
                    className="mt-2 text-xs text-blue-600 hover:text-blue-800 font-medium"
                  >
                    View pending →
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Filters & Actions Bar */}
        <div className="bg-white rounded-lg border border-gray-200 p-4 mb-4">
          <div className="flex flex-wrap items-center gap-3">
            {/* Status Filter */}
            <select value={uploadStatus} onChange={(e) => setUploadStatus(e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white">
              <option value="pending">⏳ Pending</option>
              <option value="uploaded">✅ Uploaded</option>
              <option value="errored">❌ Errored</option>
              <option value="not_ready">🔧 Not Ready</option>
              <option value="all">📋 All</option>
            </select>

            {/* Batch Filter */}
            <select value={batchFilter} onChange={(e) => setBatchFilter(e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white">
              <option value="">All Batches</option>
              {batches.map((b) => (
                <option key={b.batch_id} value={b.batch_id}>{b.batch_name}</option>
              ))}
            </select>

            {/* Search */}
            <input type="text" placeholder="Search email..." value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-lg text-sm w-48" />

            {/* Sequencer Format */}
            <select value={exportFormat} onChange={(e) => setExportFormat(e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white">
              <option value="instantly">Instantly</option>
              <option value="plusvibe">PlusVibe</option>
              <option value="smartlead">Smartlead</option>
              <option value="generic">Generic</option>
            </select>

            <div className="flex-1" />

            {/* Action Buttons */}
            {selectedIds.size > 0 && uploadStatus === "uploaded" && (
              <button onClick={handleUnmark}
                className="px-3 py-2 bg-orange-100 text-orange-700 rounded-lg text-sm font-medium hover:bg-orange-200">
                ↩ Unmark ({selectedIds.size})
              </button>
            )}
            {selectedIds.size > 0 && uploadStatus !== "uploaded" && (
              <button onClick={handleMarkUploaded}
                className="px-3 py-2 bg-green-100 text-green-700 rounded-lg text-sm font-medium hover:bg-green-200">
                ✅ Mark Uploaded ({selectedIds.size})
              </button>
            )}
            <button onClick={handleMarkAllPending}
              className="px-3 py-2 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700">
              ✅ Mark All Pending
            </button>
            <button onClick={handleExportPending}
              className="px-3 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700">
              📥 Export Pending
            </button>
            <button onClick={handleExportAll}
              className="px-3 py-2 bg-gray-600 text-white rounded-lg text-sm font-medium hover:bg-gray-700">
              📥 Export All
            </button>
          </div>
        </div>

        {/* Mailbox Table */}
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          {/* Table Header Info */}
          <div className="px-4 py-3 border-b border-gray-200 bg-gray-50 flex items-center justify-between">
            <div className="text-sm text-gray-600">
              {mailboxes ? (
                <>Showing {mailboxes.items.length} of {mailboxes.total} mailboxes
                  <span className="mx-2">|</span>
                  <span className="text-green-600">✅ {mailboxes.filter_uploaded} uploaded</span>
                  <span className="mx-1">·</span>
                  <span className="text-yellow-600">⏳ {mailboxes.filter_pending} pending</span>
                </>
              ) : "Loading..."}
            </div>
            {selectedIds.size > 0 && (
              <span className="text-sm font-medium text-blue-600">{selectedIds.size} selected</span>
            )}
          </div>

          {/* Table */}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="px-4 py-3 text-left">
                    <input type="checkbox" checked={selectAll} onChange={toggleSelectAll}
                      className="rounded border-gray-300" />
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-gray-600">Email</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-600">Domain</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-600">Batch</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-600">Status</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-600">Upload</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-600">Sequencer</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-600">Uploaded At</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {mailboxes?.items.map((mb) => (
                  <tr key={mb.id} className={`hover:bg-gray-50 ${selectedIds.has(mb.id) ? "bg-blue-50" : ""}`}>
                    <td className="px-4 py-2.5">
                      <input type="checkbox" checked={selectedIds.has(mb.id)}
                        onChange={() => toggleSelect(mb.id)} className="rounded border-gray-300" />
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs">{mb.email}</td>
                    <td className="px-4 py-2.5 text-gray-600">{mb.domain_name || "-"}</td>
                    <td className="px-4 py-2.5 text-gray-600 truncate max-w-[120px]">{mb.batch_name || "-"}</td>
                    <td className="px-4 py-2.5">
                      <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${
                        mb.setup_complete ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-600"
                      }`}>
                        {mb.setup_complete ? "Ready" : "Setup..."}
                      </span>
                    </td>
                    <td className="px-4 py-2.5">
                      {mb.upload_error ? (
                        <span className="text-xs text-red-600" title={mb.upload_error}>❌ Error</span>
                      ) : mb.uploaded_to_sequencer ? (
                        <span className="text-xs text-green-600">✅ Uploaded</span>
                      ) : mb.setup_complete ? (
                        <span className="text-xs text-yellow-600">⏳ Pending</span>
                      ) : (
                        <span className="text-xs text-gray-400">—</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-gray-500 text-xs">{mb.sequencer_name || "-"}</td>
                    <td className="px-4 py-2.5 text-gray-500 text-xs">
                      {mb.uploaded_at ? new Date(mb.uploaded_at).toLocaleDateString() : "-"}
                    </td>
                  </tr>
                ))}
                {(!mailboxes || mailboxes.items.length === 0) && (
                  <tr>
                    <td colSpan={8} className="px-4 py-12 text-center text-gray-500">
                      {loading ? "Loading mailboxes..." : "No mailboxes found for the current filter."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="px-4 py-3 border-t border-gray-200 bg-gray-50 flex items-center justify-between">
              <button onClick={() => setPage(Math.max(1, page - 1))} disabled={page <= 1}
                className="px-3 py-1.5 border border-gray-300 rounded text-sm disabled:opacity-50 hover:bg-gray-100">
                ← Previous
              </button>
              <span className="text-sm text-gray-600">
                Page {page} of {totalPages}
              </span>
              <button onClick={() => setPage(Math.min(totalPages, page + 1))} disabled={page >= totalPages}
                className="px-3 py-1.5 border border-gray-300 rounded text-sm disabled:opacity-50 hover:bg-gray-100">
                Next →
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
