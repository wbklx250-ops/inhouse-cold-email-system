"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Mailbox, MailboxStatus, Tenant, listMailboxes, listTenants } from "@/lib/api";
import { Badge } from "@/components/ui/Badge";
import { ExportButton } from "@/components/mailboxes/ExportButton";

const statusConfig: Record<MailboxStatus, { label: string; variant: "success" | "warning" | "error" | "default" }> = {
  created: { label: "Created", variant: "default" },
  configured: { label: "Configured", variant: "default" },
  uploaded: { label: "Uploaded", variant: "warning" },
  warming: { label: "Warming", variant: "warning" },
  ready: { label: "Ready", variant: "success" },
  suspended: { label: "Suspended", variant: "error" },
};

const ITEMS_PER_PAGE = 50;

export default function MailboxesPage() {
  const router = useRouter();
  const [mailboxes, setMailboxes] = useState<Mailbox[]>([]);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [tenantsMap, setTenantsMap] = useState<Record<string, Tenant>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [tenantFilter, setTenantFilter] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<MailboxStatus | "">("");

  // Pagination
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      setError(null);
      const [mailboxData, tenantData] = await Promise.all([
        listMailboxes(
          page * ITEMS_PER_PAGE,
          ITEMS_PER_PAGE,
          tenantFilter || undefined,
          statusFilter || undefined
        ),
        listTenants(),
      ]);
      setMailboxes(mailboxData);
      setTenants(tenantData);
      setHasMore(mailboxData.length === ITEMS_PER_PAGE);

      // Build tenants map for quick lookup
      const map: Record<string, Tenant> = {};
      tenantData.forEach((t) => {
        map[t.id] = t;
      });
      setTenantsMap(map);
    } catch (err) {
      console.error("Failed to fetch mailboxes:", err);
      setError("Failed to load mailboxes. Make sure the backend is running.");
    } finally {
      setLoading(false);
    }
  }, [page, tenantFilter, statusFilter]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Reset page when filters change
  useEffect(() => {
    setPage(0);
  }, [tenantFilter, statusFilter]);

  const handleRowClick = (id: string) => {
    router.push(`/mailboxes/${id}`);
  };

  const formatDate = (dateString: string): string => {
    return new Date(dateString).toLocaleDateString("en-NZ", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  };

  // Stats
  const totalMailboxes = mailboxes.length;
  const readyCount = mailboxes.filter((m) => m.status === "ready").length;
  const warmingCount = mailboxes.filter((m) => m.status === "warming").length;

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex justify-between items-center">
          <div className="h-8 w-48 bg-gray-200 rounded animate-pulse" />
          <div className="h-10 w-32 bg-gray-200 rounded animate-pulse" />
        </div>
        <div className="bg-white rounded-lg border border-gray-200 p-12 text-center">
          <div className="text-2xl animate-pulse">↻</div>
          <p className="mt-4 text-gray-500">Loading mailboxes...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Mailboxes</h1>
          <p className="text-gray-500 mt-1">
            Manage all mailboxes across tenants
          </p>
        </div>
        <ExportButton tenantId={tenantFilter || undefined} />
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-4 gap-4">
        <div className="bg-white rounded-lg border border-gray-200 px-4 py-3">
          <div className="text-2xl font-bold text-gray-900">{totalMailboxes}</div>
          <div className="text-sm text-gray-500">Showing</div>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 px-4 py-3">
          <div className="text-2xl font-bold text-green-600">{readyCount}</div>
          <div className="text-sm text-gray-500">Ready</div>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 px-4 py-3">
          <div className="text-2xl font-bold text-yellow-600">{warmingCount}</div>
          <div className="text-sm text-gray-500">Warming</div>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 px-4 py-3">
          <div className="text-2xl font-bold text-purple-600">{tenants.length}</div>
          <div className="text-sm text-gray-500">Tenants</div>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-4">
        <select
          value={tenantFilter}
          onChange={(e) => setTenantFilter(e.target.value)}
          className="px-4 py-2 border border-gray-300 rounded-lg bg-white text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
        >
          <option value="">All Tenants</option>
          {tenants.map((tenant) => (
            <option key={tenant.id} value={tenant.id}>
              {tenant.name}
            </option>
          ))}
        </select>

        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as MailboxStatus | "")}
          className="px-4 py-2 border border-gray-300 rounded-lg bg-white text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
        >
          <option value="">All Statuses</option>
          <option value="created">Created</option>
          <option value="configured">Configured</option>
          <option value="uploaded">Uploaded</option>
          <option value="warming">Warming</option>
          <option value="ready">Ready</option>
          <option value="suspended">Suspended</option>
        </select>

        {(tenantFilter || statusFilter) && (
          <button
            onClick={() => {
              setTenantFilter("");
              setStatusFilter("");
            }}
            className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800"
          >
            Clear filters
          </button>
        )}
      </div>

      {/* Error State */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 flex items-start">
          <span className="text-red-500 mr-3">!</span>
          <div>
            <h4 className="text-red-800 font-medium">Error loading mailboxes</h4>
            <p className="text-red-600 text-sm mt-1">{error}</p>
            <button
              onClick={() => {
                setLoading(true);
                fetchData();
              }}
              className="mt-2 text-sm text-red-700 underline hover:no-underline"
            >
              Try again
            </button>
          </div>
        </div>
      )}

      {/* Mailboxes Table */}
      {!error && (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          {mailboxes.length === 0 ? (
            <div className="p-12 text-center">
              <div className="text-4xl mb-4">📬</div>
              <h3 className="text-lg font-medium text-gray-900 mb-2">No mailboxes yet</h3>
              <p className="text-gray-500">
                Generate mailboxes from a tenant to get started.
              </p>
            </div>
          ) : (
            <>
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Email
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Display Name
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Tenant
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Status
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Flags
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Created
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {mailboxes.map((mailbox) => {
                    const statusInfo = statusConfig[mailbox.status];
                    const tenant = tenantsMap[mailbox.tenant_id];

                    return (
                      <tr
                        key={mailbox.id}
                        onClick={() => handleRowClick(mailbox.id)}
                        className="hover:bg-gray-50 cursor-pointer transition-colors"
                      >
                        <td className="px-6 py-4 whitespace-nowrap">
                          <code className="text-sm text-gray-900 font-mono">
                            {mailbox.email}
                          </code>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600">
                          {mailbox.display_name}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          {tenant ? (
                            <span className="text-sm text-blue-600 hover:underline">
                              {tenant.name}
                            </span>
                          ) : (
                            <span className="text-sm text-gray-400">Unknown</span>
                          )}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <Badge variant={statusInfo.variant}>{statusInfo.label}</Badge>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="flex gap-1">
                            {mailbox.account_enabled && (
                              <span className="px-1.5 py-0.5 bg-green-100 text-green-700 text-xs rounded">EN</span>
                            )}
                            {mailbox.password_set && (
                              <span className="px-1.5 py-0.5 bg-blue-100 text-blue-700 text-xs rounded">PW</span>
                            )}
                            {mailbox.upn_fixed && (
                              <span className="px-1.5 py-0.5 bg-purple-100 text-purple-700 text-xs rounded">UPN</span>
                            )}
                            {mailbox.delegated && (
                              <span className="px-1.5 py-0.5 bg-yellow-100 text-yellow-700 text-xs rounded">DEL</span>
                            )}
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                          {formatDate(mailbox.created_at)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>

              {/* Pagination */}
              <div className="px-6 py-3 border-t border-gray-200 flex items-center justify-between bg-gray-50">
                <div className="text-sm text-gray-500">
                  Showing {page * ITEMS_PER_PAGE + 1} - {page * ITEMS_PER_PAGE + mailboxes.length}
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => setPage((p) => Math.max(0, p - 1))}
                    disabled={page === 0}
                    className="px-3 py-1 border border-gray-300 rounded text-sm disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-100"
                  >
                    Previous
                  </button>
                  <button
                    onClick={() => setPage((p) => p + 1)}
                    disabled={!hasMore}
                    className="px-3 py-1 border border-gray-300 rounded text-sm disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-100"
                  >
                    Next
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}