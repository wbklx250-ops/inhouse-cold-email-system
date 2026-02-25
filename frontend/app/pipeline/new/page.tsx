"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface ValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
  summary: {
    domains_count: number;
    tenants_count: number;
    credentials_matched: number;
    credentials_unmatched: number;
    domains_linked: number;
    expected_mailboxes: number;
  };
}

export default function NewPipelinePage() {
  const router = useRouter();

  // Form state
  const [batchName, setBatchName] = useState("");
  const [domainsCsv, setDomainsCsv] = useState<File | null>(null);
  const [tenantsCsv, setTenantsCsv] = useState<File | null>(null);
  const [credentialsTxt, setCredentialsTxt] = useState<File | null>(null);
  const [profilePhoto, setProfilePhoto] = useState<File | null>(null);
  const [newAdminPassword, setNewAdminPassword] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [mailboxesPerTenant, setMailboxesPerTenant] = useState(50);
  const [sequencerPlatform, setSequencerPlatform] = useState("");
  const [sequencerEmail, setSequencerEmail] = useState("");
  const [sequencerPassword, setSequencerPassword] = useState("");

  // UI state
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [isValidating, setIsValidating] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Auto-validate when all 3 files + names are provided
  const runValidation = useCallback(async () => {
    if (!domainsCsv || !tenantsCsv || !credentialsTxt || !firstName || !lastName) return;

    setIsValidating(true);
    setError(null);

    try {
      const formData = new FormData();
      formData.append("domains_csv", domainsCsv);
      formData.append("tenants_csv", tenantsCsv);
      formData.append("credentials_txt", credentialsTxt);
      formData.append("first_name", firstName);
      formData.append("last_name", lastName);
      formData.append("mailboxes_per_tenant", String(mailboxesPerTenant));

      const res = await fetch(`${API_BASE}/api/v1/pipeline/validate`, {
        method: "POST",
        body: formData,
      });
      const data: ValidationResult = await res.json();
      setValidation(data);
    } catch {
      setError("Validation request failed");
    } finally {
      setIsValidating(false);
    }
  }, [domainsCsv, tenantsCsv, credentialsTxt, firstName, lastName, mailboxesPerTenant]);

  const handleSubmit = async () => {
    if (!batchName || !domainsCsv || !tenantsCsv || !credentialsTxt || !newAdminPassword || !firstName || !lastName) {
      setError("Please fill in all required fields");
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      const formData = new FormData();
      formData.append("batch_name", batchName);
      formData.append("domains_csv", domainsCsv);
      formData.append("tenants_csv", tenantsCsv);
      formData.append("credentials_txt", credentialsTxt);
      formData.append("new_admin_password", newAdminPassword);
      formData.append("first_name", firstName);
      formData.append("last_name", lastName);
      formData.append("mailboxes_per_tenant", String(mailboxesPerTenant));
      formData.append("sequencer_platform", sequencerPlatform);
      formData.append("sequencer_login_email", sequencerEmail);
      formData.append("sequencer_login_password", sequencerPassword);
      if (profilePhoto) {
        formData.append("profile_photo", profilePhoto);
      }

      const res = await fetch(`${API_BASE}/api/v1/pipeline/create-and-start`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail?.errors?.join(", ") || "Failed to create batch");
      }

      const data = await res.json();
      router.push(`/pipeline/${data.batch_id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to start pipeline");
    } finally {
      setIsSubmitting(false);
    }
  };

  const allFilesUploaded = domainsCsv && tenantsCsv && credentialsTxt;
  const canSubmit = batchName && allFilesUploaded && newAdminPassword && firstName && lastName && validation?.valid;

  return (
    <div className="max-w-3xl mx-auto py-8 px-4">
      <h1 className="text-2xl font-bold text-gray-900 mb-2">New Batch Setup</h1>
      <p className="text-gray-600 mb-8">
        Upload all files and configuration. The system will run the entire pipeline automatically.
      </p>

      {error && (
        <div className="mb-6 rounded-lg bg-red-50 border border-red-200 p-4 text-red-800 text-sm">
          {error}
        </div>
      )}

      <div className="space-y-8">
        {/* Batch Name */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Batch Name</label>
          <input
            type="text"
            value={batchName}
            onChange={(e) => setBatchName(e.target.value)}
            placeholder="e.g., Client ABC - March 2026"
            className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          />
        </div>

        {/* Files Section */}
        <div>
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Files</h2>
          <div className="space-y-4">
            <FileUpload
              label="Domains CSV"
              accept=".csv"
              required
              file={domainsCsv}
              onFile={(f) => { setDomainsCsv(f); setValidation(null); }}
              hint="Columns: domain, redirect_url (optional)"
            />
            <FileUpload
              label="Tenant CSV"
              accept=".csv"
              required
              file={tenantsCsv}
              onFile={(f) => { setTenantsCsv(f); setValidation(null); }}
              hint="From reseller — company name, onmicrosoft domain, etc."
            />
            <FileUpload
              label="Credentials TXT"
              accept=".txt"
              required
              file={credentialsTxt}
              onFile={(f) => { setCredentialsTxt(f); setValidation(null); }}
              hint="Username: / Password: pairs from reseller"
            />
            <FileUpload
              label="Profile Photo"
              accept=".jpg,.jpeg,.png"
              file={profilePhoto}
              onFile={setProfilePhoto}
              hint="Optional — same photo for all mailboxes"
            />
          </div>
        </div>

        {/* Tenant Configuration */}
        <div>
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Tenant Configuration</h2>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">New Admin Password</label>
            <input
              type="password"
              value={newAdminPassword}
              onChange={(e) => setNewAdminPassword(e.target.value)}
              placeholder="Min 12 chars, upper + lower + digit + special"
              className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
            />
            {newAdminPassword && newAdminPassword.length < 12 && (
              <p className="mt-1 text-xs text-red-500">Password must be at least 12 characters</p>
            )}
          </div>
        </div>

        {/* Mailbox Configuration */}
        <div>
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Mailbox Configuration</h2>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">First Name</label>
              <input
                type="text"
                value={firstName}
                onChange={(e) => { setFirstName(e.target.value); setValidation(null); }}
                placeholder="Jack"
                className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Last Name</label>
              <input
                type="text"
                value={lastName}
                onChange={(e) => { setLastName(e.target.value); setValidation(null); }}
                placeholder="Zuvelek"
                className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Mailboxes/Tenant</label>
              <input
                type="number"
                value={mailboxesPerTenant}
                onChange={(e) => setMailboxesPerTenant(Number(e.target.value))}
                min={1}
                max={50}
                className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              />
            </div>
          </div>
        </div>

        {/* Sequencer Section */}
        <div>
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Sequencer (Optional)</h2>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Platform</label>
              <select
                value={sequencerPlatform}
                onChange={(e) => setSequencerPlatform(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              >
                <option value="">— Skip sequencer upload —</option>
                <option value="plusvibe">PlusVibe</option>
                <option value="instantly">Instantly</option>
                <option value="smartlead">Smartlead</option>
              </select>
            </div>
            {sequencerPlatform && (
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Login Email</label>
                  <input
                    type="email"
                    value={sequencerEmail}
                    onChange={(e) => setSequencerEmail(e.target.value)}
                    className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Login Password</label>
                  <input
                    type="password"
                    value={sequencerPassword}
                    onChange={(e) => setSequencerPassword(e.target.value)}
                    className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                  />
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Validate Button */}
        {allFilesUploaded && firstName && lastName && !validation && (
          <button
            onClick={runValidation}
            disabled={isValidating}
            className="w-full rounded-lg bg-gray-100 border border-gray-300 py-3 text-sm font-medium text-gray-700 hover:bg-gray-200 disabled:opacity-50"
          >
            {isValidating ? "Validating..." : "Validate Files"}
          </button>
        )}

        {/* Validation Preview */}
        {validation && (
          <div className={`rounded-lg border p-5 ${validation.valid ? "bg-green-50 border-green-200" : "bg-red-50 border-red-200"}`}>
            <h3 className="font-semibold text-gray-900 mb-3">
              {validation.valid ? "✓ Ready to start" : "✗ Fix errors before starting"}
            </h3>

            {validation.errors.length > 0 && (
              <div className="mb-3">
                {validation.errors.map((err, i) => (
                  <p key={i} className="text-sm text-red-700">❌ {err}</p>
                ))}
              </div>
            )}

            {validation.warnings.length > 0 && (
              <div className="mb-3">
                {validation.warnings.map((warn, i) => (
                  <p key={i} className="text-sm text-yellow-700">⚠️ {warn}</p>
                ))}
              </div>
            )}

            <div className="grid grid-cols-3 gap-4 text-center mt-4">
              <div className="bg-white rounded-lg p-3 shadow-sm">
                <p className="text-2xl font-bold text-blue-600">{validation.summary.domains_count}</p>
                <p className="text-xs text-gray-500">Domains</p>
              </div>
              <div className="bg-white rounded-lg p-3 shadow-sm">
                <p className="text-2xl font-bold text-blue-600">{validation.summary.tenants_count}</p>
                <p className="text-xs text-gray-500">Tenants</p>
              </div>
              <div className="bg-white rounded-lg p-3 shadow-sm">
                <p className="text-2xl font-bold text-blue-600">{validation.summary.credentials_matched}</p>
                <p className="text-xs text-gray-500">Matched</p>
              </div>
              <div className="bg-white rounded-lg p-3 shadow-sm">
                <p className="text-2xl font-bold text-green-600">{validation.summary.domains_linked}</p>
                <p className="text-xs text-gray-500">Linked</p>
              </div>
              <div className="bg-white rounded-lg p-3 shadow-sm col-span-2">
                <p className="text-2xl font-bold text-purple-600">{validation.summary.expected_mailboxes.toLocaleString()}</p>
                <p className="text-xs text-gray-500">Mailboxes to create</p>
              </div>
            </div>
          </div>
        )}

        {/* Submit Button */}
        <button
          onClick={handleSubmit}
          disabled={!canSubmit || isSubmitting}
          className="w-full rounded-lg bg-blue-600 py-3.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
        >
          {isSubmitting ? "Starting Pipeline..." : "🚀 Start Batch Setup"}
        </button>
      </div>
    </div>
  );
}

// Simple file upload component
function FileUpload({
  label,
  accept,
  required,
  file,
  onFile,
  hint,
}: {
  label: string;
  accept: string;
  required?: boolean;
  file: File | null;
  onFile: (f: File | null) => void;
  hint?: string;
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">
        {label} {required && <span className="text-red-500">*</span>}
      </label>
      <div className="flex items-center gap-3">
        <label className="cursor-pointer rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm text-gray-600 hover:bg-gray-50">
          Choose File
          <input
            type="file"
            accept={accept}
            className="hidden"
            onChange={(e) => onFile(e.target.files?.[0] || null)}
          />
        </label>
        {file ? (
          <span className="text-sm text-green-700 font-medium">✓ {file.name}</span>
        ) : (
          <span className="text-sm text-gray-400">No file selected</span>
        )}
      </div>
      {hint && <p className="mt-1 text-xs text-gray-400">{hint}</p>}
    </div>
  );
}
