"use client";

import { useState, useEffect, use } from "react";
import Link from "next/link";
import { Domain, getDomain, DomainStatus } from "@/lib/api";
import { Badge } from "@/components/ui/Badge";
import { NameserverDisplay } from "@/components/domains/NameserverDisplay";
import { DomainActions } from "@/components/domains/DomainActions";

interface DomainDetailPageProps {
  params: Promise<{ id: string }>;
}

const statusConfig: Record<DomainStatus, { label: string; variant: "success" | "warning" | "error" | "default" }> = {
  purchased: { label: "Purchased", variant: "default" },
  cf_zone_pending: { label: "CF Zone Pending", variant: "warning" },
  cf_zone_active: { label: "CF Zone Active", variant: "success" },
  zone_created: { label: "Zone Created", variant: "success" },
  ns_updating: { label: "NS Updating", variant: "warning" },
  ns_propagating: { label: "NS Propagating", variant: "warning" },
  ns_propagated: { label: "NS Propagated", variant: "success" },
  dns_configuring: { label: "DNS Configuring", variant: "warning" },
  tenant_linked: { label: "Tenant Linked", variant: "warning" },
  pending_m365: { label: "Pending M365", variant: "warning" },
  m365_verified: { label: "M365 Verified", variant: "success" },
  pending_dkim: { label: "Pending DKIM", variant: "warning" },
  active: { label: "Active", variant: "success" },
  problem: { label: "Problem", variant: "error" },
  error: { label: "Error", variant: "error" },
  retired: { label: "Retired", variant: "default" },
};

const formatDate = (dateString: string): string => {
  return new Date(dateString).toLocaleDateString("en-NZ", {
    day: "2-digit",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
};

const getTLD = (domainName: string): string => {
  const parts = domainName.split(".");
  return parts.length > 1 ? `.${parts[parts.length - 1]}` : "";
};

export default function DomainDetailPage({ params }: DomainDetailPageProps) {
  const resolvedParams = use(params);
  const [domain, setDomain] = useState<Domain | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchDomain = async () => {
      try {
        setError(null);
        const data = await getDomain(resolvedParams.id);
        setDomain(data);
      } catch (err) {
        console.error("Failed to fetch domain:", err);
        setError("Failed to load domain. It may not exist or the backend is unavailable.");
      } finally {
        setLoading(false);
      }
    };

    fetchDomain();
  }, [resolvedParams.id]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <div className="text-4xl mb-4 animate-pulse">*</div>
          <p className="text-gray-500">Loading domain details...</p>
        </div>
      </div>
    );
  }

  if (error || !domain) {
    return (
      <div className="space-y-6">
        <Link href="/domains" className="text-blue-600 hover:text-blue-800 text-sm">
          Back to Domains
        </Link>
        <div className="bg-red-50 border border-red-200 rounded-lg p-6 text-center">
          <div className="text-4xl mb-4">!</div>
          <h2 className="text-lg font-medium text-red-800 mb-2">Domain Not Found</h2>
          <p className="text-red-600">{error}</p>
          <Link
            href="/domains"
            className="inline-block mt-4 px-4 py-2 bg-red-100 text-red-700 rounded-lg hover:bg-red-200"
          >
            Return to Domains List
          </Link>
        </div>
      </div>
    );
  }

  const statusInfo = statusConfig[domain.status] || { label: domain.status, variant: "default" as const };
  const dnsRecords = [
    { name: "MX Record", description: "Mail exchange routing", verified: domain.mx_configured },
    { name: "SPF Record", description: "Sender policy framework", verified: domain.spf_configured },
    { name: "DKIM Record", description: "DomainKeys verification", verified: domain.dkim_enabled },
    { name: "DMARC Record", description: "Authentication reporting", verified: domain.dmarc_configured },
  ];
  const verifiedCount = dnsRecords.filter((r) => r.verified).length;

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <Link href="/domains" className="text-blue-600 hover:text-blue-800 text-sm inline-flex items-center gap-1">
        Back to Domains
      </Link>

      {/* Domain Info Card */}
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-lg bg-blue-100 text-blue-600 text-2xl">
              G
            </div>
            <div>
              <h1 className="text-2xl font-bold text-gray-900">{domain.name}</h1>
              <p className="text-sm text-gray-500 font-mono">{domain.id}</p>
            </div>
          </div>
          <Badge variant={statusInfo.variant}>{statusInfo.label}</Badge>
        </div>

        <div className="mt-6 pt-4 border-t border-gray-100 grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">TLD</p>
            <p className="mt-1 text-sm font-medium text-gray-900">{getTLD(domain.name)}</p>
          </div>
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Created</p>
            <p className="mt-1 text-sm font-medium text-gray-900">{formatDate(domain.created_at)}</p>
          </div>
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">DNS Records</p>
            <p className="mt-1 text-sm font-medium text-gray-900">{verifiedCount}/4 verified</p>
          </div>
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Zone ID</p>
            <p className="mt-1 text-sm font-mono text-gray-600 truncate" title={domain.cloudflare_zone_id || undefined}>
              {domain.cloudflare_zone_id ? `${domain.cloudflare_zone_id.slice(0, 12)}...` : "Not assigned"}
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Cloudflare Status Card */}
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <span className="text-orange-500">CF</span>
            Cloudflare Status
          </h2>

          <div className="space-y-4">
            <div className="flex items-center justify-between py-2 border-b border-gray-100">
              <span className="text-sm text-gray-600">Zone Status</span>
              <Badge variant={domain.cloudflare_zone_id ? "success" : "warning"}>
                {domain.cloudflare_zone_id ? "Zone Created" : "Pending"}
              </Badge>
            </div>

            {domain.cloudflare_zone_id && (
              <div className="py-2 border-b border-gray-100">
                <span className="text-sm text-gray-600">Zone ID</span>
                <p className="mt-1 font-mono text-sm text-gray-900 break-all">{domain.cloudflare_zone_id}</p>
              </div>
            )}

            {domain.cloudflare_nameservers && domain.cloudflare_nameservers.length > 0 && (
              <div className="pt-2">
                <NameserverDisplay 
                  nameservers={domain.cloudflare_nameservers} 
                  showInstructions={domain.status === "cf_zone_pending"}
                />
              </div>
            )}
          </div>
        </div>

        {/* DNS Records Status Card */}
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <span className="text-purple-500">DNS</span>
            DNS Records
          </h2>

          <div className="space-y-3">
            {dnsRecords.map((record) => (
              <div
                key={record.name}
                className={`flex items-center justify-between p-3 rounded-lg ${
                  record.verified ? "bg-green-50" : "bg-gray-50"
                }`}
              >
                <div>
                  <p className={`text-sm font-medium ${record.verified ? "text-green-900" : "text-gray-700"}`}>
                    {record.name}
                  </p>
                  <p className={`text-xs ${record.verified ? "text-green-600" : "text-gray-500"}`}>
                    {record.description}
                  </p>
                </div>
                <div
                  className={`flex h-8 w-8 items-center justify-center rounded-full ${
                    record.verified ? "bg-green-100 text-green-600" : "bg-gray-100 text-gray-400"
                  }`}
                >
                  {record.verified ? "Y" : "-"}
                </div>
              </div>
            ))}
          </div>

          {verifiedCount === 4 && (
            <div className="mt-4 p-3 bg-green-50 border border-green-200 rounded-lg">
              <p className="text-sm text-green-700 font-medium">
                All DNS records are verified and propagated!
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Actions Card */}
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Actions</h2>
        <DomainActions domain={domain} onUpdate={setDomain} />
      </div>
    </div>
  );
}