"use client";

import { useState } from "react";
import { exportMailboxCredentials } from "@/lib/api";

interface ExportButtonProps {
  tenantId?: string;
  className?: string;
}

export function ExportButton({ tenantId, className = "" }: ExportButtonProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleExport = async () => {
    setLoading(true);
    setError(null);

    try {
      await exportMailboxCredentials(tenantId);
    } catch (err) {
      console.error("Failed to export credentials:", err);
      setError("Failed to export. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="inline-flex items-center gap-2">
      <button
        onClick={handleExport}
        disabled={loading}
        className={`inline-flex items-center px-4 py-2 bg-green-600 text-white text-sm font-medium rounded-lg hover:bg-green-700 transition-colors disabled:bg-green-400 disabled:cursor-not-allowed ${className}`}
      >
        {loading ? (
          <>
            <span className="animate-spin mr-2">↻</span>
            Exporting...
          </>
        ) : (
          <>
            <span className="mr-2">↓</span>
            Export CSV
          </>
        )}
      </button>
      {error && <span className="text-sm text-red-600">{error}</span>}
    </div>
  );
}