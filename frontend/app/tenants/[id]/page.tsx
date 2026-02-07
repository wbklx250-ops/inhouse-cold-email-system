"use client";

import { useState, useEffect, use } from "react";
import Link from "next/link";
import {
  TenantWithDomain,
  TenantStatus,
  Domain,
  getTenant,
  linkDomainToTenant,
  generateMailboxesLegacy,
  listDomains,
  deleteTenant,
} from "@/lib/api";
import { Badge } from "@/components/ui/Badge";

interface TenantDetailPageProps {
  params: Promise<{ id: string }>;
}

const statusConfig: Record<TenantStatus, { label: string; variant: "success" | "warning" | "error" | "default" }> = {
  // Import/creation states
  new: { label: "New", variant: "default" },
  imported: { label: "Imported", variant: "default" },
  first_login_pending: { label: "First Login Pending", variant: "default" },
  first_login_complete: { label: "First Login Complete", variant: "default" },
  // Domain linking
  domain_linked: { label: "Domain Linked", variant: "warning" },
  domain_added: { label: "Domain Added", variant: "warning" },
  // M365 connection states
  m365_connected: { label: "M365 Connected", variant: "warning" },
  domain_verified: { label: "Domain Verified", variant: "warning" },
  // DNS/DKIM configuration
  dns_configuring: { label: "DNS Configuring", variant: "warning" },
  dns_configured: { label: "DNS Configured", variant: "warning" },
  dkim_configuring: { label: "DKIM Configuring", variant: "warning" },
  pending_dkim: { label: "Pending DKIM", variant: "warning" },
  dkim_enabled: { label: "DKIM Enabled", variant: "warning" },
  // Mailbox states
  mailboxes_creating: { label: "Creating Mailboxes", variant: "warning" },
  mailboxes_configuring: { label: "Configuring Mailboxes", variant: "warning" },
  mailboxes_created: { label: "Mailboxes Created", variant: "warning" },
  configuring: { label: "Configuring", variant: "warning" },
  // Final states
  ready: { label: "Ready", variant: "success" },
  active: { label: "Active", variant: "success" },
  suspended: { label: "Suspended", variant: "error" },
  retired: { label: "Retired", variant: "default" },
  error: { label: "Error", variant: "error" },
};

const formatDate = (dateString: string): string => {
  return new Date(dateString).toLocaleDateString("en-NZ", {
    day: "2-digit",
    month: "long",
    year: "numeric",
  });
};

export default function TenantDetailPage({ params }: TenantDetailPageProps) {
  const resolvedParams = use(params);
  const [tenant, setTenant] = useState<TenantWithDomain | null>(null);
  const [availableDomains, setAvailableDomains] = useState<Domain[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Action states
  const [selectedDomainId, setSelectedDomainId] = useState<string>("");
  const [linkingDomain, setLinkingDomain] = useState(false);
  const [mailboxCount, setMailboxCount] = useState<number>(50);
  const [generatingMailboxes, setGeneratingMailboxes] = useState(false);
  const [generationResult, setGenerationResult] = useState<string | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setError(null);
        const [tenantData, domainsData] = await Promise.all([
          getTenant(resolvedParams.id),
          listDomains(),
        ]);
        setTenant(tenantData);
        // Filter to only show active domains without a tenant
        setAvailableDomains(domainsData.filter((d) => d.status === "active"));
      } catch (err) {
        console.error("Failed to fetch tenant:", err);
        setError("Failed to load tenant. It may not exist or the backend is unavailable.");
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [resolvedParams.id]);

  const handleLinkDomain = async () => {
    if (!selectedDomainId || !tenant) return;

    setLinkingDomain(true);
    try {
      const updated = await linkDomainToTenant(tenant.id, selectedDomainId);
      // Refetch to get domain info
      const refreshed = await getTenant(tenant.id);
      setTenant(refreshed);
      setSelectedDomainId("");
    } catch (err) {
      console.error("Failed to link domain:", err);
      alert("Failed to link domain. Please try again.");
    } finally {
      setLinkingDomain(false);
    }
  };

  const handleGenerateMailboxes = async () => {
    if (!tenant || mailboxCount < 1) return;

    setGeneratingMailboxes(true);
    setGenerationResult(null);
    try {
      const result = await generateMailboxesLegacy(tenant.id, mailboxCount);
      setGenerationResult(`Successfully created ${result.mailboxes_created} mailboxes`);
      // Refetch tenant to update counts
      const refreshed = await getTenant(tenant.id);
      setTenant(refreshed);
    } catch (err) {
      console.error("Failed to generate mailboxes:", err);
      setGenerationResult("Failed to generate mailboxes. Make sure a domain is linked.");
    } finally {
      setGeneratingMailboxes(false);
    }
  };

  const handleDelete = async () => {
    if (!tenant) return;

    setDeleting(true);
    try {
      await deleteTenant(tenant.id);
      window.location.href = "/tenants";
    } catch (err) {
      console.error("Failed to delete tenant:", err);
      alert("Failed to delete tenant.");
      setDeleting(false);
      setShowDeleteConfirm(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <div className="text-4xl mb-4 animate-pulse">*</div>
          <p className="text-gray-500">Loading tenant details...</p>
        </div>
      </div>
    );
  }

  if (error || !tenant) {
    return (
      <div className="space-y-6">
        <Link href="/tenants" className="text-blue-600 hover:text-blue-800 text-sm">
          Back to Tenants
        </Link>
        <div className="bg-red-50 border border-red-200 rounded-lg p-6 text-center">
          <div className="text-4xl mb-4">!</div>
          <h2 className="text-lg font-medium text-red-800 mb-2">Tenant Not Found</h2>
          <p className="text-red-600">{error}</p>
          <Link
            href="/tenants"
            className="inline-block mt-4 px-4 py-2 bg-red-100 text-red-700 rounded-lg hover:bg-red-200"
          >
            Return to Tenants List
          </Link>
        </div>
      </div>
    );
  }

  const statusInfo = statusConfig[tenant.status] || { label: tenant.status, variant: "default" as const };

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <Link href="/tenants" className="text-blue-600 hover:text-blue-800 text-sm inline-flex items-center gap-1">
        Back to Tenants
      </Link>

      {/* Tenant Info Card */}
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-lg bg-purple-100 text-purple-600 text-2xl font-bold">
              {tenant.name.charAt(0).toUpperCase()}
            </div>
            <div>
              <h1 className="text-2xl font-bold text-gray-900">{tenant.name}</h1>
              <p className="text-sm text-gray-500">{tenant.onmicrosoft_domain}</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm font-medium text-blue-600">
              Microsoft 365
            </span>
            <Badge variant={statusInfo.variant}>{statusInfo.label}</Badge>
          </div>
        </div>

        <div className="mt-6 pt-4 border-t border-gray-100 grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Tenant ID</p>
            <p className="mt-1 text-sm font-mono text-gray-600 truncate" title={tenant.microsoft_tenant_id}>
              {tenant.microsoft_tenant_id.slice(0, 12)}...
            </p>
          </div>
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Admin Email</p>
            <p className="mt-1 text-sm text-gray-900">{tenant.admin_email}</p>
          </div>
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Created</p>
            <p className="mt-1 text-sm text-gray-900">{formatDate(tenant.created_at)}</p>
          </div>
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Total Mailboxes</p>
            <p className="mt-1 text-sm font-medium text-gray-900">{tenant.mailbox_count}</p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Linked Domain Card */}
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Linked Domain</h2>

          {tenant.domain ? (
            <div className="space-y-4">
              <div className="flex items-center justify-between p-4 bg-gray-50 rounded-lg">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-100 text-blue-600">
                    G
                  </div>
                  <div>
                    <p className="font-medium text-gray-900">{tenant.domain.name}</p>
                    <p className="text-xs text-gray-500">
                      Status: {tenant.domain.status}
                    </p>
                  </div>
                </div>
                <Link
                  href={`/domains/${tenant.domain.id}`}
                  className="text-sm text-blue-600 hover:text-blue-800"
                >
                  View Domain
                </Link>
              </div>
              <div className="flex gap-2">
                {tenant.domain.mx_configured && (
                  <span className="px-2 py-1 bg-green-100 text-green-700 text-xs rounded">MX</span>
                )}
                {tenant.domain.spf_configured && (
                  <span className="px-2 py-1 bg-green-100 text-green-700 text-xs rounded">SPF</span>
                )}
                {tenant.domain.dkim_enabled && (
                  <span className="px-2 py-1 bg-green-100 text-green-700 text-xs rounded">DKIM</span>
                )}
                {tenant.domain.dmarc_configured && (
                  <span className="px-2 py-1 bg-green-100 text-green-700 text-xs rounded">DMARC</span>
                )}
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
                <p className="text-sm text-yellow-700">
                  No domain linked. Link a domain to generate mailboxes with custom email addresses.
                </p>
              </div>

              {availableDomains.length > 0 ? (
                <div className="flex gap-3">
                  <select
                    value={selectedDomainId}
                    onChange={(e) => setSelectedDomainId(e.target.value)}
                    className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="">Select a domain...</option>
                    {availableDomains.map((domain) => (
                      <option key={domain.id} value={domain.id}>
                        {domain.name}
                      </option>
                    ))}
                  </select>
                  <button
                    onClick={handleLinkDomain}
                    disabled={!selectedDomainId || linkingDomain}
                    className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
                  >
                    {linkingDomain ? "Linking..." : "Link Domain"}
                  </button>
                </div>
              ) : (
                <p className="text-sm text-gray-500">
                  No active domains available.{" "}
                  <Link href="/domains/new" className="text-blue-600 hover:underline">
                    Add a domain
                  </Link>{" "}
                  first.
                </p>
              )}
            </div>
          )}
        </div>

        {/* Mailbox Stats Card */}
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Mailbox Stats</h2>

          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="p-4 bg-gray-50 rounded-lg text-center">
                <p className="text-3xl font-bold text-gray-900">{tenant.mailbox_count}</p>
                <p className="text-sm text-gray-500">Created</p>
              </div>
              <div className="p-4 bg-green-50 rounded-lg text-center">
                <p className="text-3xl font-bold text-green-600">{tenant.mailboxes_configured}</p>
                <p className="text-sm text-gray-500">Configured</p>
              </div>
            </div>

            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span className="text-gray-600">Capacity Used</span>
                <span className="font-medium">{tenant.mailbox_count} / {tenant.target_mailbox_count}</span>
              </div>
              <div className="w-full bg-gray-200 rounded-full h-2">
                <div
                  className="bg-blue-600 h-2 rounded-full transition-all"
                  style={{ width: `${Math.min((tenant.mailbox_count / tenant.target_mailbox_count) * 100, 100)}%` }}
                />
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Actions Card */}
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Actions</h2>

        <div className="space-y-6">
          {/* Generate Mailboxes */}
          <div className="p-4 bg-gray-50 rounded-lg">
            <h3 className="font-medium text-gray-900 mb-3">Generate Mailboxes</h3>
            {tenant.domain ? (
              <div className="space-y-3">
                <div className="flex gap-3">
                  <div className="flex-1">
                    <label className="block text-sm text-gray-600 mb-1">Number of mailboxes</label>
                    <input
                      type="number"
                      min="1"
                      max="50"
                      value={mailboxCount}
                      onChange={(e) => setMailboxCount(parseInt(e.target.value) || 1)}
                      className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                  <div className="flex items-end">
                    <button
                      onClick={handleGenerateMailboxes}
                      disabled={generatingMailboxes || mailboxCount < 1}
                      className="px-6 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
                    >
                      {generatingMailboxes ? "Generating..." : "Generate"}
                    </button>
                  </div>
                </div>
                {generationResult && (
                  <p className={`text-sm ${generationResult.includes("Failed") ? "text-red-600" : "text-green-600"}`}>
                    {generationResult}
                  </p>
                )}
                <p className="text-xs text-gray-500">
                  Mailboxes will be created with the format firstname.lastname@{tenant.domain.name}
                </p>
              </div>
            ) : (
              <p className="text-sm text-yellow-600">
                Link a domain first to generate mailboxes.
              </p>
            )}
          </div>

          {/* Danger Zone */}
          <div className="border-t border-gray-200 pt-4">
            <h4 className="text-sm font-medium text-gray-500 mb-3">Danger Zone</h4>
            {!showDeleteConfirm ? (
              <button
                onClick={() => setShowDeleteConfirm(true)}
                className="text-sm text-red-600 hover:text-red-700 hover:underline"
              >
                Delete this tenant...
              </button>
            ) : (
              <div className="bg-red-50 border border-red-200 rounded-lg p-4 space-y-3">
                <p className="text-sm text-red-700">
                  Are you sure? This will delete the tenant and all {tenant.mailbox_count} associated mailboxes.
                </p>
                <div className="flex gap-3">
                  <button
                    onClick={handleDelete}
                    disabled={deleting}
                    className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:bg-gray-300"
                  >
                    {deleting ? "Deleting..." : "Yes, Delete Tenant"}
                  </button>
                  <button
                    onClick={() => setShowDeleteConfirm(false)}
                    className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}