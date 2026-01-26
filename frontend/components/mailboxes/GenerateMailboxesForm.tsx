"use client";

import { useState } from "react";
import { generateMailboxes, Mailbox } from "@/lib/api";

interface GenerateMailboxesFormProps {
  tenantId: string;
  domainName: string;
  onSuccess?: (mailboxes: Mailbox[]) => void;
}

export function GenerateMailboxesForm({ tenantId, domainName, onSuccess }: GenerateMailboxesFormProps) {
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ count: number } | null>(null);

  const generatePreview = (): string[] => {
    if (!firstName.trim() || !lastName.trim()) return [];

    const first = firstName.toLowerCase().trim();
    const last = lastName.toLowerCase().trim();
    const firstInitial = first[0] || "j";

    return [
      `${first}.${last}@${domainName}`,
      `${first}${last}@${domainName}`,
      `${firstInitial}${last}@${domainName}`,
      `${first}.${last[0]}@${domainName}`,
      `${last}.${first}@${domainName}`,
    ];
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!firstName.trim() || !lastName.trim()) {
      setError("Both first and last name are required");
      return;
    }

    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const mailboxes = await generateMailboxes(tenantId, {
        first_name: firstName.trim(),
        last_name: lastName.trim(),
      });
      setResult({ count: mailboxes.length });
      setFirstName("");
      setLastName("");
      if (onSuccess) {
        onSuccess(mailboxes);
      }
    } catch (err) {
      console.error("Failed to generate mailboxes:", err);
      setError("Failed to generate mailboxes. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const preview = generatePreview();

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6">
      <h3 className="text-lg font-semibold text-gray-900 mb-4">Generate Mailboxes</h3>
      <p className="text-sm text-gray-500 mb-4">
        Create 50 mailbox variations based on a persona name.
      </p>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label htmlFor="firstName" className="block text-sm font-medium text-gray-700 mb-1">
              First Name
            </label>
            <input
              type="text"
              id="firstName"
              value={firstName}
              onChange={(e) => setFirstName(e.target.value)}
              placeholder="e.g., John"
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
          </div>
          <div>
            <label htmlFor="lastName" className="block text-sm font-medium text-gray-700 mb-1">
              Last Name
            </label>
            <input
              type="text"
              id="lastName"
              value={lastName}
              onChange={(e) => setLastName(e.target.value)}
              placeholder="e.g., Smith"
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
          </div>
        </div>

        {/* Preview Section */}
        {preview.length > 0 && (
          <div className="bg-gray-50 rounded-lg p-4">
            <p className="text-xs font-medium text-gray-500 uppercase mb-2">Preview (5 of 50)</p>
            <div className="space-y-1">
              {preview.map((email, idx) => (
                <code key={idx} className="block text-sm text-gray-700 font-mono">
                  {email}
                </code>
              ))}
            </div>
            <p className="text-xs text-gray-400 mt-2">...and 45 more variations</p>
          </div>
        )}

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-3">
            <p className="text-sm text-red-700">{error}</p>
          </div>
        )}

        {result && (
          <div className="bg-green-50 border border-green-200 rounded-lg p-3">
            <p className="text-sm text-green-700">
              ✓ Successfully created {result.count} mailboxes!
            </p>
          </div>
        )}

        <button
          type="submit"
          disabled={loading || !firstName.trim() || !lastName.trim()}
          className="w-full px-4 py-3 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 transition-colors disabled:bg-gray-300 disabled:cursor-not-allowed flex items-center justify-center"
        >
          {loading ? (
            <>
              <span className="animate-spin mr-2">↻</span>
              Generating 50 Mailboxes...
            </>
          ) : (
            <>
              <span className="mr-2">+</span>
              Generate 50 Mailboxes
            </>
          )}
        </button>
      </form>
    </div>
  );
}