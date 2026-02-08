"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  Tenant,
  TenantStatus,
  TenantBulkImportResult,
  TenantBulkOperationResult,
  listTenants,
  bulkImportTenantsCsv,
} from "@/lib/api";
import { TenantsTable } from "@/components/tenants/TenantsTable";
import { TenantBulkImportModal } from "@/components/tenants/TenantBulkImportModal";
import { TenantImportResultsModal } from "@/components/tenants/TenantImportResultsModal";
import { TenantBulkActions } from "@/components/tenants/TenantBulkActions";
import { GenerateMailboxesModal } from "@/components/tenants/GenerateMailboxesModal";
import { ToastContainer, useToasts } from "@/components/ui/Toast";

export default function TenantsPage() {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<TenantStatus | "">("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [showImportModal, setShowImportModal] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [importResult, setImportResult] = useState<TenantBulkImportResult | null>(null);
  const [showResultsModal, setShowResultsModal] = useState(false);
  const [showGenerateModal, setShowGenerateModal] = useState(false);
  const { toasts, success, error: showError, info, dismissToast } = useToasts();

  const fetchTenants = useCallback(async () => {
    try {
      setError(null);
      const data = await listTenants(0, 500, statusFilter || undefined);
      setTenants(data);
    } catch (err) {
      console.error("Failed to fetch tenants:", err);
      setError("Failed to load tenants. Make sure the backend is running.");
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    fetchTenants();
  }, [fetchTenants]);

  const selectedTenants = tenants.filter((t) => selectedIds.includes(t.id));

  const handleImport = async (file: File) => {
    setIsImporting(true);
    try {
      const result = await bulkImportTenantsCsv(file);
      setImportResult(result);
      setShowImportModal(false);
      setShowResultsModal(true);
      if (result.created > 0) {
        success("Imported " + result.created + " tenant(s)", result.skipped + " skipped, " + result.failed + " failed");
      } else if (result.failed > 0) {
        showError("Import completed with errors", result.failed + " tenant(s) failed to import");
      } else {
        info("No new tenants imported", "All tenants were skipped (already exist)");
      }
      await fetchTenants();
    } catch (err: unknown) {
      console.error("Import failed:", err);
      const errorMessage = err instanceof Error ? err.message : "Import failed";
      showError("Import failed", errorMessage);
    } finally {
      setIsImporting(false);
    }
  };

  const handleOperationStart = (operation: string) => {
    info(operation + " started", "Processing selected tenants...");
  };

  const handleOperationComplete = async (operation: string, result: TenantBulkOperationResult) => {
    if (result.succeeded > 0) {
      success(operation + " completed", result.succeeded + " succeeded, " + result.failed + " failed");
    } else {
      showError(operation + " failed", "All " + result.failed + " tenants failed to process");
    }
    setSelectedIds([]);
    await fetchTenants();
  };

  const handleOperationError = (operation: string, errorMsg: string) => {
    showError(operation + " failed", errorMsg);
  };

  const handleGenerateSuccess = async () => {
    success("Mailboxes generated", "New mailbox records created in database");
    await fetchTenants();
  };

  const totalMailboxes = tenants.reduce((sum, t) => sum + t.mailbox_count, 0);
  const configuredMailboxes = tenants.reduce((sum, t) => sum + t.mailboxes_configured, 0);

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex justify-between items-center">
          <div className="h-8 w-48 bg-gray-200 rounded animate-pulse" />
          <div className="h-10 w-32 bg-gray-200 rounded animate-pulse" />
        </div>
        <div className="bg-white rounded-lg border border-gray-200 p-12 text-center">
          <p className="mt-4 text-gray-500">Loading tenants...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Tenants</h1>
          <p className="text-gray-500 mt-1">Manage your M365 tenants</p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => setShowImportModal(true)}
            className="inline-flex items-center px-4 py-2 bg-purple-600 text-white text-sm font-medium rounded-lg hover:bg-purple-700 transition-colors"
          >
            + Import CSV
          </button>
          <Link
            href="/tenants/new"
            className="inline-flex items-center px-4 py-2 bg-gray-100 text-gray-700 text-sm font-medium rounded-lg hover:bg-gray-200 transition-colors"
          >
            + Add Single
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-5 gap-4">
        <div className="bg-white rounded-lg border border-gray-200 px-4 py-3">
          <div className="text-2xl font-bold text-gray-900">{tenants.length}</div>
          <div className="text-sm text-gray-500">Total Tenants</div>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 px-4 py-3">
          <div className="text-2xl font-bold text-green-600">
            {tenants.filter((t) => t.status === "active").length}
          </div>
          <div className="text-sm text-gray-500">Active</div>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 px-4 py-3">
          <div className="text-2xl font-bold text-yellow-600">
            {tenants.filter((t) => ["new", "imported", "domain_linked"].includes(t.status)).length}
          </div>
          <div className="text-sm text-gray-500">Pending Setup</div>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 px-4 py-3">
          <div className="text-2xl font-bold text-purple-600">{totalMailboxes}</div>
          <div className="text-sm text-gray-500">Total Mailboxes</div>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 px-4 py-3">
          <div className="text-2xl font-bold text-blue-600">{configuredMailboxes}</div>
          <div className="text-sm text-gray-500">Configured Mailboxes</div>
        </div>
      </div>

      <div className="bg-white rounded-lg border border-gray-200 p-4">
        <h3 className="text-sm font-medium text-gray-700 mb-3">Bulk Actions</h3>
        <TenantBulkActions
          selectedTenants={selectedTenants}
          onOperationStart={handleOperationStart}
          onOperationComplete={handleOperationComplete}
          onOperationError={handleOperationError}
          onOpenGenerateMailboxes={() => setShowGenerateModal(true)}
        />
      </div>

      <div className="flex gap-4 items-center">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as TenantStatus | "")}
          className="px-4 py-2 border border-gray-300 rounded-lg bg-white text-sm focus:ring-2 focus:ring-purple-500 focus:border-purple-500"
        >
          <option value="">All Statuses</option>
          <option value="new">New</option>
          <option value="imported">Imported</option>
          <option value="first_login_pending">First Login Pending</option>
          <option value="first_login_complete">First Login Complete</option>
          <option value="domain_linked">Domain Linked</option>
          <option value="domain_added">Domain Added</option>
          <option value="m365_connected">M365 Connected</option>
          <option value="domain_verified">Domain Verified</option>
          <option value="dns_configuring">DNS Configuring</option>
          <option value="dns_configured">DNS Configured</option>
          <option value="dkim_configuring">DKIM Configuring</option>
          <option value="pending_dkim">Pending DKIM</option>
          <option value="dkim_enabled">DKIM Enabled</option>
          <option value="mailboxes_creating">Creating Mailboxes</option>
          <option value="mailboxes_configuring">Configuring Mailboxes</option>
          <option value="mailboxes_created">Mailboxes Created</option>
          <option value="configuring">Configuring</option>
          <option value="ready">Ready</option>
          <option value="active">Active</option>
          <option value="suspended">Suspended</option>
          <option value="retired">Retired</option>
          <option value="error">Error</option>
        </select>
        {statusFilter && (
          <button onClick={() => setStatusFilter("")} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800">
            Clear filter
          </button>
        )}
        {selectedIds.length > 0 && (
          <button onClick={() => setSelectedIds([])} className="px-4 py-2 text-sm text-purple-600 hover:text-purple-800">
            Clear selection ({selectedIds.length})
          </button>
        )}
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 flex items-start">
          <span className="text-red-500 mr-3">!</span>
          <div>
            <h4 className="text-red-800 font-medium">Error loading tenants</h4>
            <p className="text-red-600 text-sm mt-1">{error}</p>
            <button
              onClick={() => { setLoading(true); fetchTenants(); }}
              className="mt-2 text-sm text-red-700 underline hover:no-underline"
            >
              Try again
            </button>
          </div>
        </div>
      )}

      {!error && (
        <TenantsTable
          tenants={tenants}
          selectedIds={selectedIds}
          onSelectionChange={setSelectedIds}
        />
      )}

      <TenantBulkImportModal
        isOpen={showImportModal}
        onClose={() => setShowImportModal(false)}
        onImport={handleImport}
        isLoading={isImporting}
      />

      <TenantImportResultsModal
        isOpen={showResultsModal}
        onClose={() => setShowResultsModal(false)}
        result={importResult}
      />

      <GenerateMailboxesModal
        isOpen={showGenerateModal}
        onClose={() => setShowGenerateModal(false)}
        onSuccess={handleGenerateSuccess}
      />

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}