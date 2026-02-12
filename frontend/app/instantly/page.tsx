"use client";

import React, { useState, useEffect } from "react";
import Step8InstantlyUpload from "@/components/wizard/Step8InstantlyUpload";

interface Batch {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  tenant_count: number;
}

export default function InstantlyUploaderPage() {
  const [batches, setBatches] = useState<Batch[]>([]);
  const [selectedBatchId, setSelectedBatchId] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  useEffect(() => {
    fetchBatches();
  }, []);

  const fetchBatches = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/wizard/batches`);
      if (res.ok) {
        const data = await res.json();
        setBatches(data.batches || []);
        // Auto-select the first batch if available
        if (data.batches && data.batches.length > 0 && !selectedBatchId) {
          setSelectedBatchId(data.batches[0].id);
        }
      } else {
        setError("Failed to load batches");
      }
    } catch (err) {
      setError("Network error loading batches");
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Page Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-3">
            <span className="text-4xl">⚡</span>
            Instantly.ai Uploader
          </h1>
          <p className="mt-2 text-gray-600">
            Automatically upload mailboxes from your setup batches to Instantly.ai using Selenium automation.
          </p>
        </div>

        {/* Batch Selector */}
        <div className="bg-white rounded-lg border border-gray-200 p-6 mb-6">
          <label className="block text-sm font-medium text-gray-700 mb-3">
            Select Setup Batch
          </label>
          {loading ? (
            <div className="text-gray-500">Loading batches...</div>
          ) : error ? (
            <div className="text-red-600">{error}</div>
          ) : batches.length === 0 ? (
            <div className="text-gray-500">
              No batches found. Create a batch in the{" "}
              <a href="/setup" className="text-blue-600 hover:underline">
                Setup Wizard
              </a>{" "}
              first.
            </div>
          ) : (
            <select
              value={selectedBatchId}
              onChange={(e) => setSelectedBatchId(e.target.value)}
              className="w-full px-4 py-2.5 border border-gray-300 rounded-lg bg-white text-gray-900 focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            >
              {batches.map((batch) => (
                <option key={batch.id} value={batch.id}>
                  {batch.name} ({batch.tenant_count} tenants) -{" "}
                  {new Date(batch.created_at).toLocaleDateString()}
                </option>
              ))}
            </select>
          )}
        </div>

        {/* Upload Component */}
        {selectedBatchId && (
          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <Step8InstantlyUpload
              batchId={selectedBatchId}
              suppressAutoComplete={true}
            />
          </div>
        )}

        {!selectedBatchId && !loading && batches.length > 0 && (
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-6 text-center">
            <p className="text-blue-700">
              Please select a batch above to begin uploading mailboxes to Instantly.ai
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
