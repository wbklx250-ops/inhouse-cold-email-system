"use client";

import { useState, useEffect } from "react";
import { Tenant, listTenants, generateMailboxes } from "@/lib/api";

interface GenerateMailboxesModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  preselectedTenantId?: string;
}

export const GenerateMailboxesModal = ({
  isOpen,
  onClose,
  onSuccess,
  preselectedTenantId,
}: GenerateMailboxesModalProps) => {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [selectedTenantId, setSelectedTenantId] = useState<string>("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [count, setCount] = useState(50);
  const [isLoading, setIsLoading] = useState(false);
  const [isFetchingTenants, setIsFetchingTenants] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ created: number } | null>(null);

  useEffect(() => {
    if (isOpen) {
      fetchTenants();
      if (preselectedTenantId) {
        setSelectedTenantId(preselectedTenantId);
      }
    }
  }, [isOpen, preselectedTenantId]);

  const fetchTenants = async () => {
    setIsFetchingTenants(true);
    try {
      // Fetch tenants that are ready for mailbox generation (DKIM enabled or active)
      const allTenants = await listTenants(0, 500);
      // Filter to tenants with domains configured (dkim_enabled, active, or configuring)
      const readyTenants = allTenants.filter((t) =>
        ["dkim_enabled", "active", "dkim_configuring", "mailboxes_creating", "mailboxes_configuring", "configuring"].includes(t.status)
      );
      setTenants(readyTenants);
    } catch (err) {
      console.error("Failed to fetch tenants:", err);
      setError("Failed to load tenants");
    } finally {
      setIsFetchingTenants(false);
    }
  };

  const handleGenerate = async () => {
    if (!selectedTenantId || !firstName.trim() || !lastName.trim()) {
      setError("Please fill in all required fields");
      return;
    }

    setIsLoading(true);
    setError(null);
    setResult(null);

    try {
      const mailboxes = await generateMailboxes(selectedTenantId, {
        first_name: firstName.trim(),
        last_name: lastName.trim(),
      });
      
      setResult({ created: mailboxes.length });
      
      // Wait a moment to show success, then close
      setTimeout(() => {
        onSuccess();
        handleClose();
      }, 2000);
    } catch (err: unknown) {
      console.error("Failed to generate mailboxes:", err);
      const errorMessage = err instanceof Error ? err.message : "Failed to generate mailboxes";
      setError(errorMessage);
    } finally {
      setIsLoading(false);
    }
  };

  const handleClose = () => {
    setSelectedTenantId(preselectedTenantId || "");
    setFirstName("");
    setLastName("");
    setCount(50);
    setError(null);
    setResult(null);
    onClose();
  };

  if (!isOpen) return null;

  const selectedTenant = tenants.find((t) => t.id === selectedTenantId);

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl max-w-lg w-full mx-4">
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-xl font-semibold text-gray-900">Generate Mailboxes</h2>
          <button
            onClick={handleClose}
            className="text-gray-400 hover:text-gray-600 transition-colors"
            disabled={isLoading}
          >
            <span className="text-2xl">x</span>
          </button>
        </div>

        {/* Body */}
        <div className="p-6 space-y-5">
          {/* Success Result */}
          {result && (
            <div className="bg-green-50 border border-green-200 rounded-lg p-4">
              <div className="flex items-center gap-2">
                <span className="text-2xl text-green-600">[OK]</span>
                <div>
                  <p className="font-medium text-green-800">
                    Successfully generated {result.created} mailboxes!
                  </p>
                  <p className="text-sm text-green-600 mt-1">
                    Closing modal...
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Tenant Selection */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Select Tenant <span className="text-red-500">*</span>
            </label>
            {isFetchingTenants ? (
              <div className="flex items-center gap-2 py-2 text-gray-500">
                <span className="animate-spin">*</span>
                Loading tenants...
              </div>
            ) : (
              <select
                value={selectedTenantId}
                onChange={(e) => setSelectedTenantId(e.target.value)}
                disabled={isLoading || !!result}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-purple-500 disabled:bg-gray-100"
              >
                <option value="">-- Select a tenant --</option>
                {tenants.map((tenant) => (
                  <option key={tenant.id} value={tenant.id}>
                    {tenant.name} ({tenant.mailbox_count} mailboxes)
                  </option>
                ))}
              </select>
            )}
            {tenants.length === 0 && !isFetchingTenants && (
              <p className="mt-1 text-sm text-amber-600">
                No tenants ready for mailbox generation. Tenants must have DKIM enabled first.
              </p>
            )}
          </div>

          {/* Selected Tenant Info */}
          {selectedTenant && (
            <div className="bg-purple-50 rounded-lg p-3 text-sm">
              <p className="text-purple-800 font-medium">{selectedTenant.name}</p>
              <p className="text-purple-600 text-xs mt-1">
                Domain: {selectedTenant.domain_id ? "Linked" : "Not linked"} | 
                Status: {selectedTenant.status} | 
                Existing mailboxes: {selectedTenant.mailbox_count}
              </p>
            </div>
          )}

          {/* Persona Inputs */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                First Name <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                placeholder="e.g., John"
                disabled={isLoading || !!result}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-purple-500 disabled:bg-gray-100"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Last Name <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
                placeholder="e.g., Smith"
                disabled={isLoading || !!result}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-purple-500 disabled:bg-gray-100"
              />
            </div>
          </div>

          {/* Count Input */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Number of Mailboxes
            </label>
            <input
              type="number"
              value={count}
              onChange={(e) => setCount(Math.max(1, Math.min(100, parseInt(e.target.value) || 50)))}
              min={1}
              max={100}
              disabled={isLoading || !!result}
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-purple-500 disabled:bg-gray-100"
            />
          </div>

          {/* Note */}
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-3">
            <p className="text-sm text-blue-700">
              <span className="font-medium">Note:</span> Will generate {count} unique email addresses 
              using variations of the provided name (no numbers). Emails will be stored in the database 
              but not yet created in M365.
            </p>
          </div>

          {/* Error Message */}
          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
              Warning: {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-200 flex justify-end gap-3">
          <button
            onClick={handleClose}
            disabled={isLoading}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={handleGenerate}
            disabled={!selectedTenantId || !firstName.trim() || !lastName.trim() || isLoading || !!result}
            className="px-4 py-2 text-sm font-medium text-white bg-purple-600 rounded-lg hover:bg-purple-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {isLoading ? (
              <>
                <span className="animate-spin">*</span>
                Generating...
              </>
            ) : (
              <>
                Generate {count} Mailboxes
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
};

export default GenerateMailboxesModal;