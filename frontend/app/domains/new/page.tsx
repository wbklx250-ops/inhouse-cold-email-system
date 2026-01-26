"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createDomain, DomainWithNameservers } from "@/lib/api";

const DOMAIN_REGEX = /^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$/;

export default function NewDomainPage() {
  const router = useRouter();
  const [domainName, setDomainName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState<DomainWithNameservers | null>(null);

  const validateDomain = (value: string): string | null => {
    if (!value.trim()) {
      return "Domain name is required";
    }
    if (!DOMAIN_REGEX.test(value.trim())) {
      return "Please enter a valid domain name (e.g., example.com)";
    }
    return null;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    const validationError = validateDomain(domainName);
    if (validationError) {
      setError(validationError);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const result = await createDomain(domainName.trim().toLowerCase());
      setSuccess(result);
    } catch (err) {
      console.error("Failed to create domain:", err);
      setError("Failed to create domain. It may already exist or the backend is unavailable.");
    } finally {
      setLoading(false);
    }
  };

  const handleDomainChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setDomainName(e.target.value);
    if (error) {
      const validationError = validateDomain(e.target.value);
      if (!validationError) {
        setError(null);
      }
    }
  };

  // Success state with nameservers
  if (success) {
    return (
      <div className="max-w-2xl mx-auto">
        <div className="bg-white rounded-lg border border-gray-200 p-8">
          {/* Success Header */}
          <div className="text-center mb-8">
            <div className="inline-flex items-center justify-center w-16 h-16 bg-green-100 rounded-full mb-4">
              <span className="text-3xl">✅</span>
            </div>
            <h1 className="text-2xl font-bold text-gray-900">Domain Added Successfully!</h1>
            <p className="text-gray-500 mt-2">{success.message}</p>
          </div>

          {/* Domain Info */}
          <div className="bg-gray-50 rounded-lg p-4 mb-6">
            <div className="flex items-center gap-3">
              <span className="text-2xl">🌐</span>
              <div>
                <div className="font-medium text-gray-900">{success.domain.name}</div>
                <div className="text-sm text-gray-500 font-mono">{success.domain.id}</div>
              </div>
            </div>
          </div>

          {/* Nameservers */}
          <div className="mb-8">
            <h3 className="text-lg font-medium text-gray-900 mb-3">
              Configure Your Nameservers
            </h3>
            <p className="text-gray-600 text-sm mb-4">
              Update your domain registrar to use the following Cloudflare nameservers:
            </p>
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
              <div className="space-y-2">
                {success.nameservers.map((ns, i) => (
                  <div key={i} className="flex items-center justify-between">
                    <code className="text-blue-800 font-mono text-sm">{ns}</code>
                    <button
                      onClick={() => navigator.clipboard.writeText(ns)}
                      className="text-blue-600 hover:text-blue-800 text-xs"
                      title="Copy to clipboard"
                    >
                      📋 Copy
                    </button>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Next Steps */}
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 mb-6">
            <h4 className="font-medium text-yellow-800 mb-2">⚡ Next Steps</h4>
            <ol className="text-sm text-yellow-700 list-decimal list-inside space-y-1">
              <li>Log in to your domain registrar (GoDaddy, Namecheap, etc.)</li>
              <li>Update the nameservers to the ones shown above</li>
              <li>Wait for DNS propagation (up to 48 hours)</li>
              <li>Return here and click "Confirm Nameservers" on the domain</li>
            </ol>
          </div>

          {/* Actions */}
          <div className="flex gap-4">
            <Link
              href={`/domains/${success.domain.id}`}
              className="flex-1 inline-flex items-center justify-center px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
            >
              View Domain Details
            </Link>
            <Link
              href="/domains"
              className="flex-1 inline-flex items-center justify-center px-4 py-2 bg-gray-100 text-gray-700 text-sm font-medium rounded-lg hover:bg-gray-200 transition-colors"
            >
              Back to Domains
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto">
      {/* Breadcrumb */}
      <div className="mb-6">
        <Link href="/domains" className="text-blue-600 hover:text-blue-800 text-sm">
          ← Back to Domains
        </Link>
      </div>

      {/* Form Card */}
      <div className="bg-white rounded-lg border border-gray-200 p-8">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Add New Domain</h1>
          <p className="text-gray-500 mt-1">
            Add a domain to Cloudflare and configure it for email sending.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Domain Input */}
          <div>
            <label htmlFor="domain" className="block text-sm font-medium text-gray-700 mb-2">
              Domain Name
            </label>
            <div className="relative">
              <span className="absolute inset-y-0 left-0 pl-3 flex items-center text-gray-400">
                🌐
              </span>
              <input
                type="text"
                id="domain"
                value={domainName}
                onChange={handleDomainChange}
                placeholder="example.com"
                disabled={loading}
                className={`w-full pl-10 pr-4 py-3 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors ${
                  error
                    ? "border-red-300 bg-red-50"
                    : "border-gray-300 bg-white"
                } disabled:bg-gray-100 disabled:cursor-not-allowed`}
              />
            </div>
            {error && (
              <p className="mt-2 text-sm text-red-600 flex items-center">
                <span className="mr-1">⚠️</span>
                {error}
              </p>
            )}
            <p className="mt-2 text-sm text-gray-500">
              Enter the root domain without www (e.g., example.com, not www.example.com)
            </p>
          </div>

          {/* Info Box */}
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
            <h4 className="font-medium text-blue-800 mb-2">ℹ️ What happens next?</h4>
            <ul className="text-sm text-blue-700 space-y-1">
              <li>• Domain will be added to your Cloudflare account</li>
              <li>• You'll receive Cloudflare nameservers to configure</li>
              <li>• After NS propagation, DNS records will be created automatically</li>
            </ul>
          </div>

          {/* Submit Button */}
          <div className="flex gap-4">
            <button
              type="submit"
              disabled={loading}
              className="flex-1 inline-flex items-center justify-center px-4 py-3 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 transition-colors disabled:bg-blue-400 disabled:cursor-not-allowed"
            >
              {loading ? (
                <>
                  <span className="animate-spin mr-2">⏳</span>
                  Adding Domain...
                </>
              ) : (
                <>
                  <span className="mr-2">+</span>
                  Add Domain
                </>
              )}
            </button>
            <Link
              href="/domains"
              className="px-6 py-3 bg-gray-100 text-gray-700 font-medium rounded-lg hover:bg-gray-200 transition-colors"
            >
              Cancel
            </Link>
          </div>
        </form>
      </div>
    </div>
  );
}