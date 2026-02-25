"use client";

import { useState, useCallback } from "react";
import Link from "next/link";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface LookupResult {
  domain: string;
  is_connected: boolean;
  microsoft_tenant_id: string | null;
  organization_name: string | null;
  namespace_type: string | null;
  error: string | null;
  found_in_db: boolean;
  db_domain_id: string | null;
  db_tenant_id: string | null;
  db_tenant_name: string | null;
}

interface LookupResponse {
  total: number;
  connected: number;
  not_connected: number;
  errors: number;
  results: LookupResult[];
}

interface SyncResponse {
  total_checked: number;
  updated_links: number;
  already_linked: number;
  no_tenant_match: number;
  not_in_db: number;
  not_connected: number;
  updates: {
    domain: string;
    tenant_id: string;
    tenant_name: string;
    microsoft_tenant_id: string;
    previous_tenant_id: string | null;
  }[];
  already_linked_details: {
    domain: string;
    tenant_id: string;
    tenant_name: string;
  }[];
  no_tenant_match_details: {
    domain: string;
    microsoft_tenant_id: string;
  }[];
}

type FilterMode = "all" | "connected" | "not_connected" | "errors" | "in_db";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function DomainLookupPage() {
  const [domainInput, setDomainInput] = useState("");
  const [results, setResults] = useState<LookupResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [syncResult, setSyncResult] = useState<SyncResponse | null>(null);
  const [filter, setFilter] = useState<FilterMode>("all");

  // Parse domains from textarea
  const parseDomains = useCallback((): string[] => {
    return domainInput
      .split(/[\n,;\s]+/)
      .map((d) => d.trim().toLowerCase())
      .filter((d) => d.length > 0 && d.includes("."));
  }, [domainInput]);

  // Check domains against Microsoft
  const handleCheck = async () => {
    const domains = parseDomains();
    if (!domains.length) return;

    setLoading(true);
    setError(null);
    setResults(null);
    setSyncResult(null);

    try {
      const res = await fetch(`${API_BASE}/api/v1/domain-lookup/check`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ domains }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${res.status}`);
      }

      const data: LookupResponse = await res.json();
      setResults(data);
    } catch (err) {
      setError("Lookup failed: " + (err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  // Sync connected domains to database
  const handleSync = async () => {
    if (!results) return;

    const connectedDomains = results.results
      .filter((r) => r.is_connected && r.found_in_db && r.microsoft_tenant_id)
      .map((r) => r.domain);

    if (!connectedDomains.length) {
      setError("No connected domains found in our database to sync");
      return;
    }

    const confirmed = confirm(
      `Sync ${connectedDomains.length} domain(s) to their matched tenants in the database?\n\n` +
        "This will update the domain → tenant links for domains where:\n" +
        "• The domain exists in our database\n" +
        "• The Microsoft tenant ID matches a tenant in our database\n" +
        "• The current link differs from the matched tenant"
    );
    if (!confirmed) return;

    setSyncing(true);
    setError(null);
    setSyncResult(null);

    try {
      const res = await fetch(`${API_BASE}/api/v1/domain-lookup/sync-to-db`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ domains: connectedDomains }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${res.status}`);
      }

      const data: SyncResponse = await res.json();
      setSyncResult(data);
    } catch (err) {
      setError("Sync failed: " + (err as Error).message);
    } finally {
      setSyncing(false);
    }
  };

  // Export results as CSV
  const handleExportCSV = () => {
    if (!results) return;

    const headers = [
      "Domain",
      "Connected",
      "Microsoft Tenant ID",
      "Organization Name",
      "Namespace Type",
      "In Database",
      "DB Tenant Name",
      "Error",
    ];

    const rows = results.results.map((r) => [
      r.domain,
      r.is_connected ? "Yes" : "No",
      r.microsoft_tenant_id || "",
      r.organization_name || "",
      r.namespace_type || "",
      r.found_in_db ? "Yes" : "No",
      r.db_tenant_name || "",
      r.error || "",
    ]);

    const csvContent = [
      headers.join(","),
      ...rows.map((row) =>
        row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(",")
      ),
    ].join("\n");

    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `domain-lookup-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  // Filter results
  const filteredResults = results
    ? results.results.filter((r) => {
        switch (filter) {
          case "connected":
            return r.is_connected;
          case "not_connected":
            return !r.is_connected;
          case "errors":
            return !!r.error;
          case "in_db":
            return r.found_in_db;
          default:
            return true;
        }
      })
    : [];

  const domainCount = parseDomains().length;
  const syncableCount = results
    ? results.results.filter(
        (r) => r.is_connected && r.found_in_db && r.microsoft_tenant_id
      ).length
    : 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Domain Lookup</h1>
        <p className="text-sm text-gray-500 mt-1">
          Check domains against Microsoft&apos;s public endpoints to determine
          which M365 tenant each domain is connected to
        </p>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-red-700">{error}</p>
            <button
              onClick={() => setError(null)}
              className="text-red-400 hover:text-red-600"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* Sync Result Banner */}
      {syncResult && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
          <div className="flex items-start justify-between">
            <div className="space-y-3 flex-1">
              <p className="text-sm font-semibold text-blue-900">
                Sync Complete — {syncResult.total_checked} domains checked
              </p>

              {/* Summary grid */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-sm">
                <div className="flex items-center gap-1.5">
                  <span className="text-green-600 font-bold">{syncResult.updated_links}</span>
                  <span className="text-gray-600">newly linked</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="text-blue-600 font-bold">{syncResult.already_linked}</span>
                  <span className="text-gray-600">already linked</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="text-amber-600 font-bold">{syncResult.no_tenant_match}</span>
                  <span className="text-gray-600">no tenant match</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="text-gray-500 font-bold">{syncResult.not_connected}</span>
                  <span className="text-gray-600">not connected</span>
                </div>
              </div>

              {/* Newly linked details */}
              {syncResult.updates.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-green-700 mb-1">✅ Newly linked:</p>
                  <ul className="text-sm text-green-700 space-y-0.5">
                    {syncResult.updates.map((u, i) => (
                      <li key={i}>
                        <span className="font-mono">{u.domain}</span> → <span className="font-medium">{u.tenant_name}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Already linked info */}
              {syncResult.already_linked > 0 && (
                <p className="text-xs text-blue-600">
                  ℹ️ {syncResult.already_linked} domain{syncResult.already_linked !== 1 ? "s" : ""} already correctly linked to their tenant — no update needed.
                </p>
              )}

              {/* No tenant match warning */}
              {syncResult.no_tenant_match > 0 && (
                <div>
                  <p className="text-xs text-amber-700">
                    ⚠️ {syncResult.no_tenant_match} domain{syncResult.no_tenant_match !== 1 ? "s are" : " is"} connected to a Microsoft tenant, but that tenant ID is not in our database.
                  </p>
                </div>
              )}
            </div>
            <button
              onClick={() => setSyncResult(null)}
              className="text-blue-400 hover:text-blue-600 ml-3"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* Input Section */}
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Enter domains to check (one per line, or comma/semicolon/space
          separated)
        </label>
        <textarea
          className="w-full h-40 border border-gray-300 rounded-lg p-3 text-sm font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          placeholder={
            "microsoft.com\ngoogle.com\nexample.com\nyourdomain.com"
          }
          value={domainInput}
          onChange={(e) => setDomainInput(e.target.value)}
        />
        {domainInput && (
          <p className="text-xs text-gray-400 mt-1">
            {domainCount} domain{domainCount !== 1 ? "s" : ""} detected
            {domainCount > 500 && (
              <span className="text-red-500 ml-2">
                (max 500 per request)
              </span>
            )}
          </p>
        )}

        {/* Action Buttons */}
        <div className="mt-4 flex gap-3 flex-wrap">
          <button
            onClick={handleCheck}
            disabled={loading || domainCount === 0 || domainCount > 500}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium"
          >
            {loading ? (
              <span className="flex items-center gap-2">
                <span className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" />
                Checking {domainCount} domain{domainCount !== 1 ? "s" : ""}...
              </span>
            ) : (
              `🔍 Check ${domainCount} Domain${domainCount !== 1 ? "s" : ""}`
            )}
          </button>

          {results && (
            <>
              <button
                onClick={handleSync}
                disabled={syncing || syncableCount === 0}
                className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium"
              >
                {syncing ? (
                  <span className="flex items-center gap-2">
                    <span className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" />
                    Syncing...
                  </span>
                ) : (
                  `🔗 Sync ${syncableCount} to Database`
                )}
              </button>

              <button
                onClick={handleExportCSV}
                className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 text-sm font-medium"
              >
                📥 Export CSV
              </button>
            </>
          )}
        </div>
      </div>

      {/* Summary Stats */}
      {results && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div className="bg-white rounded-lg border border-gray-200 p-4 text-center">
            <div className="text-2xl font-bold text-gray-900">
              {results.total}
            </div>
            <div className="text-sm text-gray-500">Total</div>
          </div>
          <div className="bg-green-50 rounded-lg border border-green-200 p-4 text-center">
            <div className="text-2xl font-bold text-green-600">
              {results.connected}
            </div>
            <div className="text-sm text-gray-500">Connected</div>
          </div>
          <div className="bg-red-50 rounded-lg border border-red-200 p-4 text-center">
            <div className="text-2xl font-bold text-red-600">
              {results.not_connected}
            </div>
            <div className="text-sm text-gray-500">Not Connected</div>
          </div>
          <div className="bg-yellow-50 rounded-lg border border-yellow-200 p-4 text-center">
            <div className="text-2xl font-bold text-yellow-600">
              {results.errors}
            </div>
            <div className="text-sm text-gray-500">Errors</div>
          </div>
          <div className="bg-blue-50 rounded-lg border border-blue-200 p-4 text-center">
            <div className="text-2xl font-bold text-blue-600">
              {results.results.filter((r) => r.found_in_db).length}
            </div>
            <div className="text-sm text-gray-500">In Our DB</div>
          </div>
        </div>
      )}

      {/* Filter Tabs */}
      {results && (
        <div className="flex gap-1 bg-gray-100 rounded-lg p-1 w-fit flex-wrap">
          {(
            [
              ["all", "All", results.total],
              ["connected", "Connected", results.connected],
              ["not_connected", "Not Connected", results.not_connected],
              ["errors", "Errors", results.errors],
              [
                "in_db",
                "In DB",
                results.results.filter((r) => r.found_in_db).length,
              ],
            ] as [FilterMode, string, number][]
          ).map(([key, label, count]) => (
            <button
              key={key}
              onClick={() => setFilter(key)}
              className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                filter === key
                  ? "bg-white shadow text-gray-900"
                  : "text-gray-500 hover:text-gray-700"
              }`}
            >
              {label} ({count})
            </button>
          ))}
        </div>
      )}

      {/* Results Table */}
      {results && (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Domain
                  </th>
                  <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Connected
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Microsoft Tenant ID
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Organization
                  </th>
                  <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Type
                  </th>
                  <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider">
                    In DB
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Our Tenant
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {filteredResults.map((r, i) => (
                  <tr
                    key={i}
                    className={
                      r.error
                        ? "bg-yellow-50"
                        : r.is_connected
                          ? "bg-green-50/50"
                          : "bg-red-50/50"
                    }
                  >
                    <td className="px-4 py-3 text-sm font-mono text-gray-900 whitespace-nowrap">
                      {r.domain}
                    </td>
                    <td className="px-4 py-3 text-center whitespace-nowrap">
                      {r.error ? (
                        <span
                          className="text-yellow-500 cursor-help"
                          title={r.error}
                        >
                          ⚠️
                        </span>
                      ) : r.is_connected ? (
                        <span className="text-green-600">✅</span>
                      ) : (
                        <span className="text-red-500">❌</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600 font-mono whitespace-nowrap">
                      {r.microsoft_tenant_id ? (
                        <span
                          className="cursor-pointer hover:text-blue-600"
                          title="Click to copy"
                          onClick={() => {
                            navigator.clipboard.writeText(
                              r.microsoft_tenant_id!
                            );
                          }}
                        >
                          {r.microsoft_tenant_id.slice(0, 8)}…
                        </span>
                      ) : (
                        <span className="text-gray-400">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-700 max-w-[200px] truncate">
                      {r.organization_name || (
                        <span className="text-gray-400">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-center whitespace-nowrap">
                      {r.namespace_type ? (
                        <span
                          className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                            r.namespace_type === "Managed"
                              ? "bg-blue-100 text-blue-700"
                              : r.namespace_type === "Federated"
                                ? "bg-purple-100 text-purple-700"
                                : "bg-gray-100 text-gray-600"
                          }`}
                        >
                          {r.namespace_type}
                        </span>
                      ) : (
                        <span className="text-gray-400">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-center whitespace-nowrap">
                      {r.found_in_db ? (
                        <span className="text-green-600">✅</span>
                      ) : (
                        <span className="text-gray-400">❌</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm whitespace-nowrap">
                      {r.db_tenant_id ? (
                        <Link
                          href={`/tenants`}
                          className="text-blue-600 hover:text-blue-800 hover:underline font-medium"
                        >
                          {r.db_tenant_name || "View Tenant"}
                        </Link>
                      ) : (
                        <span className="text-gray-400">—</span>
                      )}
                    </td>
                  </tr>
                ))}
                {filteredResults.length === 0 && (
                  <tr>
                    <td
                      colSpan={7}
                      className="px-4 py-8 text-center text-sm text-gray-500"
                    >
                      No results match the selected filter
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Table Footer */}
          <div className="bg-gray-50 px-4 py-3 border-t border-gray-200 text-sm text-gray-500">
            Showing {filteredResults.length} of {results.total} results
            {filter !== "all" && (
              <button
                onClick={() => setFilter("all")}
                className="ml-2 text-blue-600 hover:text-blue-800 underline"
              >
                Show all
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
