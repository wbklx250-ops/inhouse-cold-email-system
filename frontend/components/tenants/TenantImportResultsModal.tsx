"use client";

import { TenantBulkImportResult } from "@/lib/api";

interface TenantImportResultsModalProps {
  isOpen: boolean;
  onClose: () => void;
  result: TenantBulkImportResult | null;
}

export const TenantImportResultsModal = ({
  isOpen,
  onClose,
  result,
}: TenantImportResultsModalProps) => {
  if (!isOpen || !result) return null;

  const { total, created, skipped, failed, results } = result;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl max-w-2xl w-full mx-4 max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between flex-shrink-0">
          <h2 className="text-xl font-semibold text-gray-900">Import Results</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 transition-colors"
          >
            <span className="text-2xl">x</span>
          </button>
        </div>

        {/* Summary */}
        <div className="px-6 py-4 border-b border-gray-100 flex-shrink-0">
          <div className="grid grid-cols-4 gap-4">
            <div className="text-center">
              <div className="text-2xl font-bold text-gray-900">{total}</div>
              <div className="text-xs text-gray-500">Total</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-green-600">{created}</div>
              <div className="text-xs text-gray-500">Created</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-yellow-600">{skipped}</div>
              <div className="text-xs text-gray-500">Skipped</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-red-600">{failed}</div>
              <div className="text-xs text-gray-500">Failed</div>
            </div>
          </div>
        </div>

        {/* Results List */}
        <div className="flex-1 overflow-auto px-6 py-4">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50 sticky top-0">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                  Row
                </th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                  Tenant
                </th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                  Status
                </th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                  Details
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {results.map((item, index) => (
                <tr key={index} className="hover:bg-gray-50">
                  <td className="px-4 py-2 whitespace-nowrap text-sm text-gray-500">
                    {item.row}
                  </td>
                  <td className="px-4 py-2 whitespace-nowrap">
                    <span className="text-sm font-medium text-gray-900">
                      {item.tenant}
                    </span>
                  </td>
                  <td className="px-4 py-2 whitespace-nowrap">
                    <span
                      className={`
                        inline-flex items-center px-2 py-1 rounded-full text-xs font-medium
                        ${item.status === "created"
                          ? "bg-green-100 text-green-800"
                          : item.status === "skipped"
                          ? "bg-yellow-100 text-yellow-800"
                          : "bg-red-100 text-red-800"
                        }
                      `}
                    >
                      {item.status === "created" && "[OK] "}
                      {item.status === "skipped" && "[SKIP] "}
                      {item.status === "failed" && "[ERR] "}
                      {item.status.charAt(0).toUpperCase() + item.status.slice(1)}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-sm text-gray-500 max-w-xs truncate" title={item.reason}>
                    {item.reason}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {results.length === 0 && (
            <div className="text-center py-8 text-gray-500">
              No results to display
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-200 flex justify-end flex-shrink-0">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-white bg-purple-600 rounded-lg hover:bg-purple-700 transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};

export default TenantImportResultsModal;