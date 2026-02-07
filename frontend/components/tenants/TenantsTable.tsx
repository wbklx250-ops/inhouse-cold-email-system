"use client";

import { useRouter } from "next/navigation";
import { Tenant, TenantStatus } from "@/lib/api";
import { Badge } from "@/components/ui/Badge";

interface TenantsTableProps {
  tenants: Tenant[];
  selectedIds: string[];
  onSelectionChange: (ids: string[]) => void;
}

const statusConfig: Record<TenantStatus, { label: string; variant: "success" | "warning" | "error" | "default" | "info"; step?: number }> = {
  new: { label: "New", variant: "default", step: 1 },
  imported: { label: "Imported", variant: "default", step: 1 },
  first_login_pending: { label: "First Login Pending", variant: "default", step: 1 },
  first_login_complete: { label: "First Login Complete", variant: "info", step: 1 },
  domain_linked: { label: "Domain Linked", variant: "info", step: 2 },
  domain_added: { label: "Domain Added", variant: "info", step: 3 },
  m365_connected: { label: "M365 Connected", variant: "info", step: 3 },
  domain_verified: { label: "M365 Verified", variant: "warning", step: 3 },
  dns_configuring: { label: "DNS Configuring", variant: "warning", step: 4 },
  dns_configured: { label: "DNS Configured", variant: "warning", step: 4 },
  dkim_configuring: { label: "DKIM Configuring", variant: "warning", step: 5 },
  pending_dkim: { label: "Pending DKIM", variant: "warning", step: 5 },
  dkim_enabled: { label: "DKIM Enabled", variant: "warning", step: 5 },
  mailboxes_creating: { label: "Creating Mailboxes", variant: "warning", step: 6 },
  mailboxes_configuring: { label: "Configuring Mailboxes", variant: "warning", step: 6 },
  mailboxes_created: { label: "Mailboxes Created", variant: "warning", step: 6 },
  configuring: { label: "Configuring", variant: "warning", step: 6 },
  ready: { label: "Ready", variant: "success", step: 7 },
  active: { label: "Active", variant: "success", step: 7 },
  suspended: { label: "Suspended", variant: "error" },
  retired: { label: "Retired", variant: "default" },
  error: { label: "Error", variant: "error" },
};

const formatDate = (dateString: string): string => {
  return new Date(dateString).toLocaleDateString("en-NZ", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
};

const PipelineProgress = ({ status }: { status: TenantStatus }) => {
  const currentStep = statusConfig[status]?.step || 0;
  const totalSteps = 7;
  if (currentStep === 0) return null;
  return (
    <div className="flex items-center gap-1 mt-1">
      {Array.from({ length: totalSteps }, (_, i) => {
        const step = i + 1;
        const isCompleted = step < currentStep;
        const isCurrent = step === currentStep;
        return (
          <div
            key={step}
            className={`h-1 w-3 rounded-full transition-colors ${
              isCompleted ? "bg-green-500" : isCurrent ? "bg-purple-500" : "bg-gray-200"
            }`}
            title={`Step ${step}`}
          />
        );
      })}
    </div>
  );
};

export function TenantsTable({ tenants, selectedIds, onSelectionChange }: TenantsTableProps) {
  const router = useRouter();

  const handleRowClick = (id: string, e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('input[type="checkbox"]')) {
      return;
    }
    router.push(`/tenants/${id}`);
  };

  const handleSelectAll = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.checked) {
      onSelectionChange(tenants.map((t) => t.id));
    } else {
      onSelectionChange([]);
    }
  };

  const handleSelectOne = (id: string, checked: boolean) => {
    if (checked) {
      onSelectionChange([...selectedIds, id]);
    } else {
      onSelectionChange(selectedIds.filter((selectedId) => selectedId !== id));
    }
  };

  const isAllSelected = tenants.length > 0 && selectedIds.length === tenants.length;
  const isSomeSelected = selectedIds.length > 0 && selectedIds.length < tenants.length;

  if (tenants.length === 0) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-12 text-center">
        <div className="text-4xl mb-4">[T]</div>
        <h3 className="text-lg font-medium text-gray-900 mb-2">No tenants yet</h3>
        <p className="text-gray-500 mb-4">Import your first M365 tenant to get started.</p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-4 py-3 w-12">
              <input
                type="checkbox"
                checked={isAllSelected}
                ref={(el) => { if (el) el.indeterminate = isSomeSelected; }}
                onChange={handleSelectAll}
                className="h-4 w-4 text-purple-600 border-gray-300 rounded focus:ring-purple-500"
              />
            </th>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Tenant</th>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Microsoft Tenant ID</th>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Mailboxes</th>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Created</th>
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-200">
          {tenants.map((tenant) => {
            const statusInfo = statusConfig[tenant.status];
            const isSelected = selectedIds.includes(tenant.id);
            return (
              <tr
                key={tenant.id}
                onClick={(e) => handleRowClick(tenant.id, e)}
                className={`hover:bg-gray-50 cursor-pointer transition-colors ${isSelected ? "bg-purple-50" : ""}`}
              >
                <td className="px-4 py-4 w-12" onClick={(e) => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={(e) => handleSelectOne(tenant.id, e.target.checked)}
                    className="h-4 w-4 text-purple-600 border-gray-300 rounded focus:ring-purple-500"
                  />
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  <div className="flex items-center">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-100 text-purple-600 font-medium">
                      {tenant.name.charAt(0).toUpperCase()}
                    </div>
                    <div className="ml-3">
                      <div className="text-sm font-medium text-gray-900">{tenant.name}</div>
                      <div className="text-xs text-gray-500">{tenant.onmicrosoft_domain}</div>
                    </div>
                  </div>
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  <code className="text-xs text-gray-600 font-mono bg-gray-50 px-2 py-1 rounded">
                    {tenant.microsoft_tenant_id.slice(0, 8)}...
                  </code>
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  <div>
                    <Badge variant={statusInfo.variant}>{statusInfo.label}</Badge>
                    <PipelineProgress status={tenant.status} />
                  </div>
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-gray-900">{tenant.mailbox_count}</span>
                    <span className="text-xs text-gray-500">({tenant.mailboxes_configured} configured)</span>
                  </div>
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{formatDate(tenant.created_at)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}