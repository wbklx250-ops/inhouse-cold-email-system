"use client";

import { BulkImportResult } from "@/lib/api";

interface ImportResultsModalProps {
  isOpen: boolean;
  onClose: () => void;
  results: BulkImportResult | null;
}

export const ImportResultsModal = ({
  isOpen,
  onClose,
  results,
}: ImportResultsModalProps) => {
  if (!isOpen || !results) return null;

  const getStatusColor = (status: string) => {
    switch (status) {
      case "created":
        return "bg-green-100 text-green-800 border-green-200";
      case "skipped":
        return "bg-yellow-100 text-yellow-800 border-yellow-200";
      case "failed":
        return "bg-red-100 text-red-800 border-red-200";
      default:
        return "bg-gray-100 text-gray-800 border-gray-200";
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "created":
        return "✅";
      case "skipped":
        return "⏭️";
      case "failed":
        return "❌";
      default:
        return "•";
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl max-w-2xl w-full mx-4 max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between shrink-0">
          <h2 className="text-xl font-semibold text-gray-900">Import Results</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 transition-colors"
          >
            <span className="text-2xl">×</span>
          </button>
        </div>

        {/* Summary Cards */}
        <div className="p-6 border-b border-gray-200 shrink-0">
          <div className="grid grid-cols-4 gap-4">
            <div className="bg-gray-50 rounded-lg p-3 text-center">
              <div className="text-2xl font-bold text-gray-900">{results.total}</div>
              <div className="text-xs text-gray-500 mt-1">Total</div>
            </div>
            <div className="bg-green-50 rounded-lg p-3 text-center border border-green-200">
              <div className="text-2xl font-bold text-green-600">{results.created}</div>
              <div className="text-xs text-green-600 mt-1">Created</div>
            </div>
            <div className="bg-yellow-50 rounded-lg p-3 text-center border border-yellow-200">
              <div className="text-2xl font-bold text-yellow-600">{results.skipped}</div>
              <div className="text-xs text-yellow-600 mt-1">Skipped</div>
            </div>
            <div className="bg-red-50 rounded-lg p-3 text-center border border-red-200">
              <div className="text-2xl font-bold text-red-600">{results.failed}</div>
              <div className="text-xs text-red-600 mt-1">Failed</div>
            </div>
          </div>
        </div>

        {/* Scrollable Results List */}
        <div className="flex-1 overflow-y-auto p-6">
          <h3 className="text-sm font-medium text-gray-700 mb-3">Detailed Results</h3>
          
          {results.results.length === 0 ? (
            <p className="text-gray-500 text-sm">No results to display.</p>
          ) : (
            <div className="space-y-2">
              {results.results.map((item, index) => (
                <div
                  key={`${item.domain}-${index}`}
                  className={`flex items-center justify-between px-3 py-2 rounded-lg border ${getStatusColor(item.status)}`}
                >
                  <div className="flex items-center gap-2">
                    <span>{getStatusIcon(item.status)}</span>
                    <span className="font-mono text-sm">{item.domain}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium uppercase">{item.status}</span>
                    {item.reason && (
                      <span className="text-xs opacity-75">({item.reason})</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-200 flex justify-between items-center shrink-0">
          <div className="text-sm text-gray-500">
            {results.created > 0 && (
              <span className="text-green-600 font-medium">
                {results.created} domain{results.created !== 1 ? "s" : ""} ready for zone creation
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
};

export default ImportResultsModal;