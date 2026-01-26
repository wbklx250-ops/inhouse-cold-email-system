"use client";

import { useState } from "react";
import { NameserverGroup } from "@/lib/api";

interface NameserverGroupsDisplayProps {
  groups: NameserverGroup[];
  totalDomains: number;
  onClose?: () => void;
}

interface NameserverGroupCardProps {
  group: NameserverGroup;
}

const NameserverGroupCard = ({ group }: NameserverGroupCardProps) => {
  const [showAll, setShowAll] = useState(false);
  const [copied, setCopied] = useState(false);
  
  const MAX_VISIBLE_DOMAINS = 5;
  const visibleDomains = showAll 
    ? group.domains 
    : group.domains.slice(0, MAX_VISIBLE_DOMAINS);
  const hiddenCount = group.domains.length - MAX_VISIBLE_DOMAINS;

  const copyNameservers = async () => {
    const nsText = group.nameservers.join("\n");
    try {
      await navigator.clipboard.writeText(nsText);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("Failed to copy:", err);
    }
  };

  return (
    <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-lg">📋</span>
          <span className="font-medium text-gray-900">
            Nameservers ({group.domain_count} domain{group.domain_count !== 1 ? "s" : ""})
          </span>
        </div>
        <button
          onClick={copyNameservers}
          className={`px-3 py-1 text-xs font-medium rounded transition-colors flex items-center gap-1 ${
            copied 
              ? "bg-green-100 text-green-700 border border-green-300" 
              : "bg-blue-100 text-blue-700 hover:bg-blue-200 border border-blue-300"
          }`}
        >
          {copied ? (
            <>
              <span>✓</span>
              Copied!
            </>
          ) : (
            <>
              <span>📋</span>
              Copy NS
            </>
          )}
        </button>
      </div>

      {/* Nameservers */}
      <div className="px-4 py-3 border-b border-gray-100 bg-blue-50/50">
        {group.nameservers.map((ns, index) => (
          <div key={ns} className="flex items-center gap-2 py-1">
            <span className="text-xs font-medium text-gray-500 w-8">
              NS{index + 1}:
            </span>
            <code className="text-sm text-blue-700 font-mono">{ns}</code>
          </div>
        ))}
      </div>

      {/* Domains */}
      <div className="px-4 py-3">
        <div className="text-sm text-gray-600">
          {visibleDomains.map((domain, index) => (
            <span key={domain}>
              <span className="font-mono text-gray-800">{domain}</span>
              {index < visibleDomains.length - 1 && (
                <span className="text-gray-400">, </span>
              )}
            </span>
          ))}
          {!showAll && hiddenCount > 0 && (
            <span className="text-gray-400">...</span>
          )}
        </div>
        
        {hiddenCount > 0 && (
          <button
            onClick={() => setShowAll(!showAll)}
            className="mt-2 text-sm text-blue-600 hover:text-blue-800 font-medium"
          >
            {showAll ? "Show less" : `Show all ${group.domain_count}`}
          </button>
        )}
      </div>
    </div>
  );
};

export const NameserverGroupsDisplay = ({
  groups,
  totalDomains,
  onClose,
}: NameserverGroupsDisplayProps) => {
  if (groups.length === 0) {
    return (
      <div className="bg-gray-50 border border-gray-200 rounded-lg p-6 text-center">
        <span className="text-4xl">📭</span>
        <p className="mt-2 text-gray-600">No nameserver groups to display</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Summary Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-gray-900">
            Nameserver Groups
          </h3>
          <p className="text-sm text-gray-500 mt-1">
            {totalDomains} domain{totalDomains !== 1 ? "s" : ""} across {groups.length} nameserver group{groups.length !== 1 ? "s" : ""}
          </p>
        </div>
        {onClose && (
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 transition-colors"
          >
            <span className="text-xl">×</span>
          </button>
        )}
      </div>

      {/* Info Box */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 text-sm text-blue-800">
        <div className="flex items-start gap-2">
          <span className="text-blue-500">💡</span>
          <div>
            <p className="font-medium">Next Step: Update Nameservers at Registrar</p>
            <p className="mt-1 text-blue-700">
              Copy the nameservers for each group and update them at your registrar (e.g., Porkbun). 
              You can bulk-update domains that share the same nameserver pair.
            </p>
          </div>
        </div>
      </div>

      {/* Nameserver Group Cards */}
      <div className="space-y-4">
        {groups.map((group, index) => (
          <NameserverGroupCard key={`${group.nameservers.join("-")}-${index}`} group={group} />
        ))}
      </div>
    </div>
  );
};

// Modal version of the display
interface NameserverGroupsModalProps {
  isOpen: boolean;
  onClose: () => void;
  groups: NameserverGroup[];
  totalDomains: number;
}

export const NameserverGroupsModal = ({
  isOpen,
  onClose,
  groups,
  totalDomains,
}: NameserverGroupsModalProps) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl max-w-3xl w-full mx-4 max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between shrink-0">
          <div>
            <h2 className="text-xl font-semibold text-gray-900">Zone Creation Complete</h2>
            <p className="text-sm text-gray-500 mt-1">
              Review nameserver groups and update at your registrar
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 transition-colors"
          >
            <span className="text-2xl">×</span>
          </button>
        </div>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto p-6">
          <NameserverGroupsDisplay 
            groups={groups} 
            totalDomains={totalDomains}
          />
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-200 flex justify-end shrink-0">
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

export default NameserverGroupsDisplay;