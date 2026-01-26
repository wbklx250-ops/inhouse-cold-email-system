"use client";

import { useState } from "react";

interface NameserverDisplayProps {
  nameservers: string[];
  showInstructions?: boolean;
}

export function NameserverDisplay({ nameservers, showInstructions = true }: NameserverDisplayProps) {
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

  const copyToClipboard = async (text: string, index: number) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedIndex(index);
      setTimeout(() => setCopiedIndex(null), 2000);
    } catch (err) {
      console.error("Failed to copy:", err);
    }
  };

  const copyAll = async () => {
    try {
      await navigator.clipboard.writeText(nameservers.join("\n"));
      setCopiedIndex(-1);
      setTimeout(() => setCopiedIndex(null), 2000);
    } catch (err) {
      console.error("Failed to copy:", err);
    }
  };

  if (!nameservers || nameservers.length === 0) {
    return (
      <div className="text-gray-500 text-sm italic">
        Nameservers not available yet
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {showInstructions && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
          <h4 className="font-medium text-amber-800 flex items-center gap-2">
            <span>!</span>
            Update Your Nameservers
          </h4>
          <p className="text-sm text-amber-700 mt-1">
            Log in to your domain registrar (GoDaddy, Namecheap, etc.) and replace your current nameservers with the ones below.
          </p>
        </div>
      )}

      <div className="space-y-2">
        {nameservers.map((ns, index) => (
          <div
            key={index}
            className="flex items-center justify-between bg-gray-50 border border-gray-200 rounded-lg px-4 py-3"
          >
            <div className="flex items-center gap-3">
              <span className="text-gray-400 text-sm font-medium">NS{index + 1}</span>
              <code className="text-gray-900 font-mono text-sm">{ns}</code>
            </div>
            <button
              onClick={() => copyToClipboard(ns, index)}
              className={`px-3 py-1 text-xs font-medium rounded transition-colors ${
                copiedIndex === index
                  ? "bg-green-100 text-green-700"
                  : "bg-gray-100 text-gray-600 hover:bg-gray-200"
              }`}
            >
              {copiedIndex === index ? "Copied!" : "Copy"}
            </button>
          </div>
        ))}
      </div>

      <button
        onClick={copyAll}
        className={`w-full px-4 py-2 text-sm font-medium rounded-lg border transition-colors ${
          copiedIndex === -1
            ? "bg-green-50 border-green-200 text-green-700"
            : "bg-white border-gray-200 text-gray-600 hover:bg-gray-50"
        }`}
      >
        {copiedIndex === -1 ? "All Copied!" : "Copy All Nameservers"}
      </button>

      {showInstructions && (
        <div className="text-sm text-gray-500 space-y-1">
          <p><strong>Note:</strong> DNS changes can take up to 48 hours to propagate worldwide.</p>
          <p>Once updated, return here and click the confirmation button below.</p>
        </div>
      )}
    </div>
  );
}