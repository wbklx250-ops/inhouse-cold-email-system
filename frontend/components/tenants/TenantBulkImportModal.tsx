"use client";

import { useState, useRef, DragEvent } from "react";

interface TenantBulkImportModalProps {
  isOpen: boolean;
  onClose: () => void;
  onImport: (file: File) => Promise<void>;
  isLoading: boolean;
}

export const TenantBulkImportModal = ({
  isOpen,
  onClose,
  onImport,
  isLoading,
}: TenantBulkImportModalProps) => {
  const [isDragging, setIsDragging] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  if (!isOpen) return null;

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    setError(null);

    const files = e.dataTransfer.files;
    if (files.length > 0) {
      validateAndSetFile(files[0]);
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    setError(null);
    const files = e.target.files;
    if (files && files.length > 0) {
      validateAndSetFile(files[0]);
    }
  };

  const validateAndSetFile = (file: File) => {
    // Check file type
    if (!file.name.endsWith(".csv")) {
      setError("Please upload a CSV file");
      return;
    }

    // Check file size (max 10MB)
    if (file.size > 10 * 1024 * 1024) {
      setError("File size must be less than 10MB");
      return;
    }

    setSelectedFile(file);
  };

  const handleImport = async () => {
    if (!selectedFile) return;
    await onImport(selectedFile);
  };

  const downloadTemplate = () => {
    const csvContent = `tenant_name,microsoft_tenant_id,onmicrosoft_domain,admin_email,admin_password,provider,licensed_user_email,domain_name
Acme Corp,12345678-1234-1234-1234-123456789012,acmecorp.onmicrosoft.com,admin@acmecorp.onmicrosoft.com,SecurePass123!,Altigen,user@acmecorp.onmicrosoft.com,acmecorp.com
TechStart Inc,87654321-4321-4321-4321-987654321098,techstart.onmicrosoft.com,admin@techstart.onmicrosoft.com,MyPassword456!,Altigen,user@techstart.onmicrosoft.com,techstart.io`;
    const blob = new Blob([csvContent], { type: "text/csv" });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "tenants_template.csv";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.URL.revokeObjectURL(url);
  };

  const handleClose = () => {
    setSelectedFile(null);
    setError(null);
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl max-w-2xl w-full mx-4">
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-xl font-semibold text-gray-900">Import Tenants from CSV</h2>
          <button
            onClick={handleClose}
            className="text-gray-400 hover:text-gray-600 transition-colors"
            disabled={isLoading}
          >
            <span className="text-2xl">x</span>
          </button>
        </div>

        {/* Body */}
        <div className="p-6 space-y-4">
          {/* Expected Format */}
          <div className="bg-gray-50 rounded-lg p-4">
            <p className="text-sm font-medium text-gray-700 mb-2">Required CSV Columns:</p>
            <code className="text-xs text-gray-600 bg-gray-100 px-2 py-1 rounded block overflow-x-auto">
              tenant_name,microsoft_tenant_id,onmicrosoft_domain,admin_email,admin_password,provider,licensed_user_email,domain_name
            </code>
            <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-gray-500">
              <div>
                <p>* <strong>tenant_name</strong>: Display name (required)</p>
                <p>* <strong>microsoft_tenant_id</strong>: UUID (required)</p>
                <p>* <strong>onmicrosoft_domain</strong>: *.onmicrosoft.com (required)</p>
                <p>* <strong>admin_email</strong>: Admin email (required)</p>
              </div>
              <div>
                <p>* <strong>admin_password</strong>: Admin password (required)</p>
                <p>* <strong>provider</strong>: e.g., Altigen (required)</p>
                <p>* <strong>licensed_user_email</strong>: Optional</p>
                <p>* <strong>domain_name</strong>: Auto-links domain (optional)</p>
              </div>
            </div>
          </div>

          {/* Download Template Button */}
          <button
            onClick={downloadTemplate}
            className="text-purple-600 hover:text-purple-800 text-sm font-medium flex items-center gap-1"
          >
            [Download] CSV Template
          </button>

          {/* Drop Zone */}
          <div
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`
              border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors
              ${isDragging 
                ? "border-purple-500 bg-purple-50" 
                : selectedFile 
                  ? "border-green-500 bg-green-50" 
                  : "border-gray-300 hover:border-gray-400 bg-gray-50"
              }
            `}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv"
              onChange={handleFileSelect}
              className="hidden"
            />
            
            {selectedFile ? (
              <div>
                <span className="text-4xl text-green-600">[OK]</span>
                <p className="mt-2 text-sm font-medium text-gray-900">{selectedFile.name}</p>
                <p className="text-xs text-gray-500 mt-1">
                  {(selectedFile.size / 1024).toFixed(1)} KB
                </p>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectedFile(null);
                  }}
                  className="mt-2 text-sm text-red-600 hover:text-red-800"
                >
                  Remove
                </button>
              </div>
            ) : (
              <div>
                <span className="text-4xl text-gray-400">[CSV]</span>
                <p className="mt-2 text-sm font-medium text-gray-900">
                  Drop your CSV file here, or click to browse
                </p>
                <p className="text-xs text-gray-500 mt-1">
                  Max file size: 10MB
                </p>
              </div>
            )}
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
            onClick={handleImport}
            disabled={!selectedFile || isLoading}
            className="px-4 py-2 text-sm font-medium text-white bg-purple-600 rounded-lg hover:bg-purple-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {isLoading ? (
              <>
                <span className="animate-spin">*</span>
                Importing...
              </>
            ) : (
              <>
                Import Tenants
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
};

export default TenantBulkImportModal;