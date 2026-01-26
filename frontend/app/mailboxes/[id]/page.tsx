"use client";

import { useState, useEffect, use } from "react";
import Link from "next/link";
import {
  Mailbox,
  MailboxStatus,
  WarmupStage,
  Tenant,
  getMailbox,
  getTenant,
  updateMailbox,
  deleteMailbox,
} from "@/lib/api";
import { Badge } from "@/components/ui/Badge";

interface MailboxDetailPageProps {
  params: Promise<{ id: string }>;
}

const statusConfig: Record<MailboxStatus, { label: string; variant: "success" | "warning" | "error" | "default" }> = {
  created: { label: "Created", variant: "default" },
  configured: { label: "Configured", variant: "default" },
  uploaded: { label: "Uploaded", variant: "warning" },
  warming: { label: "Warming", variant: "warning" },
  ready: { label: "Ready", variant: "success" },
  suspended: { label: "Suspended", variant: "error" },
};

const warmupConfig: Record<WarmupStage, { label: string; color: string }> = {
  none: { label: "None", color: "bg-gray-100 text-gray-700" },
  early: { label: "Early", color: "bg-blue-100 text-blue-700" },
  ramping: { label: "Ramping", color: "bg-yellow-100 text-yellow-700" },
  mature: { label: "Mature", color: "bg-green-100 text-green-700" },
  complete: { label: "Complete", color: "bg-purple-100 text-purple-700" },
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

export default function MailboxDetailPage({ params }: MailboxDetailPageProps) {
  const resolvedParams = use(params);
  const [mailbox, setMailbox] = useState<Mailbox | null>(null);
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // UI State
  const [showPassword, setShowPassword] = useState(false);
  const [showSuspendConfirm, setShowSuspendConfirm] = useState(false);
  const [suspending, setSuspending] = useState(false);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setError(null);
        const mailboxData = await getMailbox(resolvedParams.id);
        setMailbox(mailboxData);

        // Fetch tenant info
        try {
          const tenantData = await getTenant(mailboxData.tenant_id);
          setTenant(tenantData);
        } catch {
          // Tenant fetch failed, continue without it
        }
      } catch (err) {
        console.error("Failed to fetch mailbox:", err);
        setError("Failed to load mailbox. It may not exist or the backend is unavailable.");
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [resolvedParams.id]);

  const handleSuspend = async () => {
    if (!mailbox) return;

    setSuspending(true);
    try {
      await deleteMailbox(mailbox.id);
      // Refresh mailbox data
      const updated = await getMailbox(mailbox.id);
      setMailbox(updated);
      setShowSuspendConfirm(false);
    } catch (err) {
      console.error("Failed to suspend mailbox:", err);
      alert("Failed to suspend mailbox.");
    } finally {
      setSuspending(false);
    }
  };

  const handleToggleFlag = async (flag: "account_enabled" | "password_set" | "upn_fixed" | "delegated") => {
    if (!mailbox) return;

    try {
      const updated = await updateMailbox(mailbox.id, {
        [flag]: !mailbox[flag],
      });
      setMailbox(updated);
    } catch (err) {
      console.error(`Failed to toggle ${flag}:`, err);
      alert(`Failed to update ${flag}.`);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <div className="text-4xl mb-4 animate-pulse">↻</div>
          <p className="text-gray-500">Loading mailbox details...</p>
        </div>
      </div>
    );
  }

  if (error || !mailbox) {
    return (
      <div className="space-y-6">
        <Link href="/mailboxes" className="text-blue-600 hover:text-blue-800 text-sm">
          ← Back to Mailboxes
        </Link>
        <div className="bg-red-50 border border-red-200 rounded-lg p-6 text-center">
          <div className="text-4xl mb-4">!</div>
          <h2 className="text-lg font-medium text-red-800 mb-2">Mailbox Not Found</h2>
          <p className="text-red-600">{error}</p>
          <Link
            href="/mailboxes"
            className="inline-block mt-4 px-4 py-2 bg-red-100 text-red-700 rounded-lg hover:bg-red-200"
          >
            Return to Mailboxes List
          </Link>
        </div>
      </div>
    );
  }

  const statusInfo = statusConfig[mailbox.status];
  const warmupInfo = warmupConfig[mailbox.warmup_stage];

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <Link href="/mailboxes" className="text-blue-600 hover:text-blue-800 text-sm inline-flex items-center gap-1">
        ← Back to Mailboxes
      </Link>

      {/* Mailbox Info Card */}
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-lg bg-blue-100 text-blue-600 text-2xl font-bold">
              📧
            </div>
            <div>
              <h1 className="text-xl font-bold text-gray-900 font-mono">{mailbox.email}</h1>
              <p className="text-sm text-gray-500">{mailbox.display_name}</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className={`px-2 py-1 rounded-full text-xs font-medium ${warmupInfo.color}`}>
              Warmup: {warmupInfo.label}
            </span>
            <Badge variant={statusInfo.variant}>{statusInfo.label}</Badge>
          </div>
        </div>

        {/* Parent Tenant Link */}
        {tenant && (
          <div className="mt-4 pt-4 border-t border-gray-100">
            <p className="text-xs text-gray-500 mb-1">Parent Tenant</p>
            <Link
              href={`/tenants/${tenant.id}`}
              className="inline-flex items-center gap-2 text-blue-600 hover:text-blue-800"
            >
              <span className="flex h-6 w-6 items-center justify-center rounded bg-purple-100 text-purple-600 text-xs font-medium">
                {tenant.name.charAt(0).toUpperCase()}
              </span>
              <span className="font-medium">{tenant.name}</span>
              <span className="text-gray-400">→</span>
            </Link>
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Credentials Card */}
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Credentials</h2>

          <div className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">
                Email Address
              </label>
              <div className="flex items-center gap-2">
                <code className="flex-1 px-3 py-2 bg-gray-50 rounded-lg font-mono text-sm">
                  {mailbox.email}
                </code>
                <button
                  onClick={() => navigator.clipboard.writeText(mailbox.email)}
                  className="px-3 py-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg"
                  title="Copy email"
                >
                  📋
                </button>
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">
                Password
              </label>
              <div className="flex items-center gap-2">
                <code className="flex-1 px-3 py-2 bg-gray-50 rounded-lg font-mono text-sm">
                  {showPassword ? mailbox.password : "••••••••••••••••"}
                </code>
                <button
                  onClick={() => setShowPassword(!showPassword)}
                  className="px-3 py-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg"
                  title={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? "🙈" : "👁️"}
                </button>
                <button
                  onClick={() => navigator.clipboard.writeText(mailbox.password)}
                  className="px-3 py-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg"
                  title="Copy password"
                >
                  📋
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Status Flags Card */}
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Status Flags</h2>

          <div className="space-y-3">
            <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
              <div>
                <p className="font-medium text-gray-900">Account Enabled</p>
                <p className="text-xs text-gray-500">User can sign in to this mailbox</p>
              </div>
              <button
                onClick={() => handleToggleFlag("account_enabled")}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  mailbox.account_enabled ? "bg-green-500" : "bg-gray-300"
                }`}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    mailbox.account_enabled ? "translate-x-6" : "translate-x-1"
                  }`}
                />
              </button>
            </div>

            <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
              <div>
                <p className="font-medium text-gray-900">Password Set</p>
                <p className="text-xs text-gray-500">Password has been configured in M365</p>
              </div>
              <button
                onClick={() => handleToggleFlag("password_set")}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  mailbox.password_set ? "bg-green-500" : "bg-gray-300"
                }`}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    mailbox.password_set ? "translate-x-6" : "translate-x-1"
                  }`}
                />
              </button>
            </div>

            <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
              <div>
                <p className="font-medium text-gray-900">UPN Fixed</p>
                <p className="text-xs text-gray-500">User Principal Name matches email</p>
              </div>
              <button
                onClick={() => handleToggleFlag("upn_fixed")}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  mailbox.upn_fixed ? "bg-green-500" : "bg-gray-300"
                }`}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    mailbox.upn_fixed ? "translate-x-6" : "translate-x-1"
                  }`}
                />
              </button>
            </div>

            <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
              <div>
                <p className="font-medium text-gray-900">Delegated</p>
                <p className="text-xs text-gray-500">Delegation access configured</p>
              </div>
              <button
                onClick={() => handleToggleFlag("delegated")}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  mailbox.delegated ? "bg-green-500" : "bg-gray-300"
                }`}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    mailbox.delegated ? "translate-x-6" : "translate-x-1"
                  }`}
                />
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Details Card */}
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Details</h2>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Mailbox ID</p>
            <p className="mt-1 text-sm font-mono text-gray-600 truncate" title={mailbox.id}>
              {mailbox.id.slice(0, 12)}...
            </p>
          </div>
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Tenant ID</p>
            <p className="mt-1 text-sm font-mono text-gray-600 truncate" title={mailbox.tenant_id}>
              {mailbox.tenant_id.slice(0, 12)}...
            </p>
          </div>
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Created</p>
            <p className="mt-1 text-sm text-gray-900">{formatDate(mailbox.created_at)}</p>
          </div>
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Updated</p>
            <p className="mt-1 text-sm text-gray-900">{formatDate(mailbox.updated_at)}</p>
          </div>
        </div>
      </div>

      {/* Danger Zone */}
      {mailbox.status !== "suspended" && (
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h2 className="text-sm font-medium text-gray-500 mb-4">Danger Zone</h2>

          {!showSuspendConfirm ? (
            <button
              onClick={() => setShowSuspendConfirm(true)}
              className="text-sm text-red-600 hover:text-red-700 hover:underline"
            >
              Suspend this mailbox...
            </button>
          ) : (
            <div className="bg-red-50 border border-red-200 rounded-lg p-4 space-y-3">
              <p className="text-sm text-red-700">
                Are you sure? This will disable the mailbox and prevent it from sending/receiving emails.
              </p>
              <div className="flex gap-3">
                <button
                  onClick={handleSuspend}
                  disabled={suspending}
                  className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:bg-gray-300"
                >
                  {suspending ? "Suspending..." : "Yes, Suspend Mailbox"}
                </button>
                <button
                  onClick={() => setShowSuspendConfirm(false)}
                  className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}