"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Step7SequencerPrep from "@/components/wizard/Step7SequencerPrep";
import Step8SequencerUpload from "@/components/wizard/Step8SequencerUpload";

interface WizardStatus {
  batch_id: string;
  batch_name: string;
  current_step: number;
  step_name: string;
  can_proceed: boolean;
  status: string;
  sequencer_app_key?: string;
  sequencer_app_name?: string;
  domains_total: number;
  zones_created: number;
  zones_pending: number;
  ns_propagated: number;
  ns_pending: number;
  redirects_configured: number;
  tenants_total: number;
  tenants_linked: number;
  tenants_m365_verified: number;
  tenants_dkim_enabled: number;
  mailboxes_total: number;
  mailboxes_pending: number;
  mailboxes_ready: number;
}

interface StepResult {
  success: boolean;
  message: string;
  details?: Record<string, any>;
}

interface NameserverGroup {
  nameservers: string[];
  domain_count: number;
  domains: string[];
  propagated_count?: number;
  pending_count?: number;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchStatus(batchId: string): Promise<WizardStatus> {
  const res = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/status`);
  if (!res.ok) throw new Error("Failed to fetch status");
  return res.json();
}

async function postStep(batchId: string, endpoint: string, formData?: FormData): Promise<StepResult> {
  const res = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}${endpoint}`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(error.detail || "Request failed");
  }
  return res.json();
}

async function setStep(batchId: string, step: number): Promise<any> {
  const res = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/set-step`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ step }),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(error.detail || "Request failed");
  }
  return res.json();
}

async function rerunStep(batchId: string, stepNumber: number, force: boolean = true): Promise<any> {
  const res = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/rerun-step/${stepNumber}?force=${force}`, {
    method: "POST",
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(error.detail || "Request failed");
  }
  return res.json();
}

export default function BatchWizard() {
  const params = useParams();
  const router = useRouter();
  const batchId = params.batchId as string;

  const [status, setStatus] = useState<WizardStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeStep, setActiveStep] = useState(1);
  const [nameserversConfirmed, setNameserversConfirmed] = useState(false);
  const [suppressStep7AutoComplete, setSuppressStep7AutoComplete] = useState(false);

  useEffect(() => {
    if (batchId) {
      setNameserversConfirmed(false);
      setSuppressStep7AutoComplete(false);
      loadStatus();
    }
  }, [batchId]);

  const loadStatus = async () => {
    try {
      setLoading(true);
      const data = await fetchStatus(batchId);
      setStatus(data);
      setActiveStep(data.current_step);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="bg-red-50 border border-red-200 rounded-lg p-6 max-w-md text-center">
          <p className="text-red-800 font-medium mb-4">Error: {error}</p>
          <button onClick={() => router.push("/setup")} className="text-blue-600 hover:underline">
            ← Back to Batches
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="bg-white shadow">
        <div className="max-w-4xl mx-auto px-4 py-6">
          <button
            onClick={() => router.push("/setup")}
            className="text-blue-600 hover:underline text-sm mb-2 inline-block"
          >
            ← All Batches
          </button>
          <h1 className="text-2xl font-bold text-gray-900">{status?.batch_name}</h1>
          <p className="text-gray-600 mt-1">
            Step {activeStep > 8 ? 8 : activeStep} of 8 • {status?.status === "completed" ? "Completed" : "In Progress"}
          </p>
        </div>
      </div>

      <div className="max-w-4xl mx-auto px-4 py-6">
        <StepProgress 
          currentStep={activeStep} 
          batchId={batchId} 
          onStepClick={async (step) => {
            // Navigate to the clicked step
            try {
              setSuppressStep7AutoComplete(step === 7);
              await setStep(batchId, step);
              setActiveStep(step);
              await loadStatus();
            } catch (e) {
              console.error("Failed to navigate to step:", e);
            }
          }}
        />
      </div>

      {/* Step Navigation Bar */}
      <div className="max-w-4xl mx-auto px-4 mb-4">
        <StepNavigation
          batchId={batchId}
          currentStep={activeStep}
          onNavigate={async (step) => {
            try {
              setSuppressStep7AutoComplete(step === 7);
              await setStep(batchId, step);
              setActiveStep(step);
              await loadStatus();
            } catch (e) {
              console.error("Failed to navigate:", e);
            }
          }}
          onRerun={async (step) => {
            try {
              const result = await rerunStep(batchId, step);
              alert(result.message);
              await loadStatus();
            } catch (e) {
              alert(`Failed to rerun step: ${e instanceof Error ? e.message : "Unknown error"}`);
            }
          }}
        />
      </div>

      <div className="max-w-4xl mx-auto px-4 pb-12">
        <div className="bg-white rounded-lg shadow-lg p-8">
          {activeStep === 1 && <Step1Domains batchId={batchId} status={status} onComplete={loadStatus} />}
          {activeStep === 2 && (
            <Step2Zones
              batchId={batchId}
              status={status}
              onComplete={loadStatus}
              nameserversConfirmed={nameserversConfirmed}
              onConfirmNameservers={async () => {
                setNameserversConfirmed(true);
                await loadStatus();
                setActiveStep(3);
              }}
            />
          )}
          {activeStep === 3 && <Step3Propagation batchId={batchId} status={status} onComplete={loadStatus} onNext={() => setActiveStep(4)} />}
          {activeStep === 4 && <Step4Tenants batchId={batchId} status={status} onComplete={loadStatus} />}
          {activeStep === 5 && <Step5M365 batchId={batchId} status={status} onComplete={loadStatus} onNext={() => setActiveStep(6)} />}
          {activeStep === 6 && <Step6Mailboxes batchId={batchId} status={status} onComplete={loadStatus} onNext={() => { setSuppressStep7AutoComplete(false); setActiveStep(7); }} />}
          {activeStep === 7 && (
            <Step7SequencerPrep
              batchId={batchId}
              suppressAutoComplete={suppressStep7AutoComplete}
              onComplete={() => { setSuppressStep7AutoComplete(false); setActiveStep(8); }}
            />
          )}
          {activeStep === 8 && (
            <Step8SequencerUpload
              batchId={batchId}
              onComplete={() => { setActiveStep(9); }}
            />
          )}
          {activeStep === 9 && (
            <StepComplete 
              batchId={batchId} 
              status={status} 
              onGoBack={async (step) => {
                try {
                  setSuppressStep7AutoComplete(step === 7);
                  await setStep(batchId, step);
                  setActiveStep(step);
                  await loadStatus();
                } catch (e) {
                  console.error("Failed to navigate back:", e);
                }
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// ============== STEP COMPONENTS ==============
// These are the same as before, but pass batchId to postStep()

interface StepProgressProps {
  currentStep: number;
  batchId?: string;
  onStepClick?: (step: number) => void;
}

function StepProgress({ currentStep, batchId, onStepClick }: StepProgressProps) {
  const steps = [
    { num: 1, name: "Domains" },
    { num: 2, name: "Zones" },
    { num: 3, name: "Nameservers" },
    { num: 4, name: "Tenants" },
    { num: 5, name: "Email Setup" },
    { num: 6, name: "Mailboxes" },
    { num: 7, name: "Sequencer" },
  ];

  return (
    <div className="flex items-center justify-between">
      {steps.map((step, i) => (
        <div key={step.num} className="flex items-center">
          <button
            onClick={() => onStepClick?.(step.num)}
            disabled={!onStepClick}
            className={`w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm transition-all
              ${currentStep > step.num ? "bg-green-500 text-white hover:bg-green-600" : ""}
              ${currentStep === step.num ? "bg-blue-600 text-white ring-2 ring-blue-300" : ""}
              ${currentStep < step.num ? "bg-gray-200 text-gray-500 hover:bg-gray-300" : ""}
              ${onStepClick ? "cursor-pointer" : "cursor-default"}`}
            title={`Go to Step ${step.num}: ${step.name}`}
          >
            {currentStep > step.num ? "✓" : step.num}
          </button>
          <span className="ml-2 text-sm font-medium hidden sm:inline">{step.name}</span>
          {i < steps.length - 1 && <div className="w-8 lg:w-16 h-1 mx-2 bg-gray-200" />}
        </div>
      ))}
    </div>
  );
}

interface StepNavigationProps {
  batchId: string;
  currentStep: number;
  onNavigate: (step: number) => void;
  onRerun: (step: number) => void;
}

function StepNavigation({ batchId, currentStep, onNavigate, onRerun }: StepNavigationProps) {
  const [rerunning, setRerunning] = useState<number | null>(null);


  // Steps that support re-run automation
  const rerunableSteps = [4, 5, 6, 7];
  const stepNames: Record<number, string> = {
    1: "Domains",
    2: "Zones", 
    3: "Nameservers",
    4: "Tenants",
    5: "Email Setup",
    6: "Mailboxes",
    7: "Sequencer",
    8: "Complete",
  };

  const handleRerun = async (step: number) => {
    setRerunning(step);
    try {
      await onRerun(step);
    } finally {
      setRerunning(null);
    }
  };

  return (
    <div className="bg-white border rounded-lg p-4 shadow-sm">
      <div className="flex items-center justify-between">
        {/* Previous/Next Navigation */}
        <div className="flex items-center gap-3">
          <button
            onClick={() => onNavigate(currentStep - 1)}
            disabled={currentStep <= 1}
            className={`px-4 py-2 rounded-lg font-medium flex items-center gap-2 transition-colors
              ${currentStep <= 1 
                ? "bg-gray-100 text-gray-400 cursor-not-allowed" 
                : "bg-gray-200 text-gray-700 hover:bg-gray-300"
              }`}
          >
            ← Previous
          </button>
          
          <span className="text-sm text-gray-600 font-medium">
            Step {currentStep}: {stepNames[currentStep] || "Complete"}
          </span>

          <button
            onClick={() => onNavigate(currentStep + 1)}
            disabled={currentStep >= 7}
            className={`px-4 py-2 rounded-lg font-medium flex items-center gap-2 transition-colors
              ${currentStep >= 7 
                ? "bg-gray-100 text-gray-400 cursor-not-allowed" 
                : "bg-blue-600 text-white hover:bg-blue-700"
              }`}
          >
            Next →
          </button>
        </div>

        {/* Re-run Button for Current Step */}
        <div className="flex items-center gap-2">
          {rerunableSteps.includes(currentStep) && (
            <button
              onClick={() => handleRerun(currentStep)}
              disabled={rerunning !== null}
              className={`px-4 py-2 rounded-lg font-medium flex items-center gap-2 transition-colors
                ${rerunning !== null
                  ? "bg-orange-100 text-orange-400 cursor-not-allowed"
                  : "bg-orange-500 text-white hover:bg-orange-600"
                }`}
              title={`Re-run Step ${currentStep} automation`}
            >
              {rerunning === currentStep ? (
                <>
                  <span className="animate-spin">⟳</span>
                  Rerunning...
                </>
              ) : (
                <>
                  🔄 Re-run Step {currentStep}
                </>
              )}
            </button>
          )}
          
          {/* Quick jump dropdown for all steps */}
          <select
            value={currentStep > 7 ? 7 : currentStep}
            onChange={(e) => onNavigate(parseInt(e.target.value))}
            className="px-3 py-2 border rounded-lg text-sm bg-white hover:bg-gray-50 cursor-pointer"
            title="Jump to step"
          >
            {[1, 2, 3, 4, 5, 6, 7].map((step) => (
              <option key={step} value={step}>
                Step {step}: {stepNames[step]}
              </option>
            ))}
          </select>
        </div>
      </div>
    </div>
  );
}

function Step1Domains({ batchId, status, onComplete }: { batchId: string; status: WizardStatus | null; onComplete: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [result, setResult] = useState<StepResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [previewResult, setPreviewResult] = useState<any>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const newDomains = Array.isArray(previewResult?.new_domains) ? previewResult.new_domains : [];
  const existingDomains = Array.isArray(previewResult?.existing_domains) ? previewResult.existing_domains : [];

  const getDomainName = (entry: any) => {
    if (typeof entry === "string") return entry;
    return entry?.name || entry?.domain || "Unknown domain";
  };

  const handlePreview = async () => {
    if (!file) return;
    setPreviewing(true);
    setError(null);
    setPreviewResult(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/step1/preview-domains`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Preview failed" }));
        throw new Error(err.detail || "Preview failed");
      }
      const data = await res.json();
      setPreviewResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Preview failed");
    } finally {
      setPreviewing(false);
    }
  };

  const handleImport = async () => {
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await postStep(batchId, "/step1/import-domains", formData);
      setResult(res);
      setPreviewResult(null);
      onComplete();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed");
    } finally {
      setLoading(false);
    }
  };

  const downloadTemplate = () => {
    // Updated template with redirect column for per-domain redirects
    const csv = `domain,redirect,registrar
coldreach.io,https://google.com,porkbun
outbound-mail.co,https://example.com,porkbun
salesflow.net,https://company-website.com,porkbun`;
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "domains_template.csv";
    a.click();
  };

  if (status && status.domains_total > 0) {
    return (
      <div className="text-center py-8">
        <div className="text-6xl mb-4">✅</div>
        <h2 className="text-xl font-bold">Domains Imported!</h2>
        <p className="text-gray-600 mt-2">{status.domains_total} domains ready</p>
        <button onClick={onComplete} className="mt-6 px-6 py-3 bg-blue-600 text-white font-bold rounded-lg hover:bg-blue-700">
          Continue →
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold">Step 1: Upload Your Domains</h2>
        <p className="text-gray-600 mt-2">Upload a CSV file with your cold email domains.</p>
      </div>

      <div className="border-2 border-dashed border-gray-300 rounded-lg p-12 text-center hover:border-blue-500 cursor-pointer"
        onClick={() => fileInputRef.current?.click()}>
        <input type="file" ref={fileInputRef} className="hidden" accept=".csv" onChange={(e) => setFile(e.target.files?.[0] || null)} />
        <div className="text-5xl mb-4">📄</div>
        <p className="text-lg font-medium">{file ? file.name : "Drag & drop CSV here"}</p>
        <button type="button" onClick={(e) => { e.stopPropagation(); downloadTemplate(); }} className="mt-4 text-blue-600 underline">
          Download Template
        </button>
      </div>

      {/* CSV Format Info */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <p className="text-blue-800 font-medium">📋 CSV Format</p>
        <div className="mt-2 text-sm text-blue-700 font-mono bg-white rounded p-2 overflow-x-auto">
          <pre>{`domain,redirect,registrar
coldreach.io,https://google.com,porkbun
outbound-mail.co,https://example.com,porkbun`}</pre>
        </div>
        <p className="text-xs text-blue-600 mt-2">
          Include a <strong>redirect</strong> column to specify where each domain should redirect. Leave empty if no redirect needed.
        </p>
      </div>

      {error && <div className="bg-red-50 border border-red-200 rounded-lg p-4"><p className="text-red-800">{error}</p></div>}
      
      {/* Preview Results */}
      {previewResult && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 space-y-3">
          <div className="flex justify-between items-center">
            <h3 className="font-bold text-blue-900">Preview Results</h3>
            <button onClick={() => setPreviewResult(null)} className="text-blue-600 hover:text-blue-800 text-sm">✕ Close</button>
          </div>
          
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-green-100 rounded-lg p-3 text-center">
              <p className="text-2xl font-bold text-green-700">{previewResult.new_count}</p>
              <p className="text-xs text-green-600">New Domains</p>
            </div>
            <div className="bg-gray-100 rounded-lg p-3 text-center">
              <p className="text-2xl font-bold text-gray-700">{previewResult.existing_count}</p>
              <p className="text-xs text-gray-600">Already Exist</p>
            </div>
          </div>

          {newDomains.length > 0 && (
            <details className="text-sm">
              <summary className="cursor-pointer text-green-700 font-medium">
                Show {previewResult.new_count} new domain(s)
              </summary>
              <ul className="mt-2 ml-4 space-y-1 text-green-600">
                {newDomains.map((domain: any, i: number) => (
                  <li key={i}>• {getDomainName(domain)}</li>
                ))}
              </ul>
            </details>
          )}

          {existingDomains.length > 0 && (
            <details className="text-sm">
              <summary className="cursor-pointer text-gray-700 font-medium">
                Show {previewResult.existing_count} existing domain(s)
              </summary>
              <ul className="mt-2 ml-4 space-y-1 text-gray-500 max-h-32 overflow-y-auto">
                {existingDomains.map((item: any, i: number) => (
                  <li key={i} className="text-xs">
                    • {getDomainName(item)}{" "}
                    <span className="text-gray-400">
                      (Batch: {item.batch_name || item.batch?.batch_name || "Unknown"}, Status: {item.status || "unknown"})
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          )}

          {previewResult.new_count === 0 && (
            <p className="text-yellow-700 text-sm">⚠️ All domains already exist in the system. Nothing new to import.</p>
          )}
        </div>
      )}

      {result && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4">
          <p className="text-green-800">✅ {result.message}</p>
          {result.details?.with_redirect !== undefined && (
            <p className="text-sm text-green-700 mt-1">
              {result.details.with_redirect} domain(s) have redirect URLs configured
            </p>
          )}
        </div>
      )}

      {/* Action Buttons */}
      {!previewResult ? (
        <div className="grid grid-cols-2 gap-4">
          <button onClick={handlePreview} disabled={!file || previewing}
            className="py-4 bg-gray-600 text-white font-bold rounded-lg hover:bg-gray-700 disabled:bg-gray-300">
            {previewing ? "Previewing..." : "Preview Domains"}
          </button>
          <button onClick={handleImport} disabled={!file || loading}
            className="py-4 bg-blue-600 text-white font-bold rounded-lg hover:bg-blue-700 disabled:bg-gray-300">
            {loading ? "Importing..." : "Import Domains →"}
          </button>
        </div>
      ) : (
        <button 
          onClick={handleImport} 
          disabled={!file || loading || previewResult.new_count === 0}
          className="w-full py-4 bg-green-600 text-white font-bold rounded-lg hover:bg-green-700 disabled:bg-gray-300">
          {loading ? "Importing..." : `Import ${previewResult.new_count} New Domain(s) →`}
        </button>
      )}
    </div>
  );
}

// Continue with Step2Zones, Step3Propagation, Step4Tenants, Step5M365, Step6Mailboxes, StepComplete
// Each one follows the same pattern: pass batchId to postStep(batchId, "/stepX/...", formData)

function Step2Zones({
  batchId,
  status,
  onComplete,
  nameserversConfirmed,
  onConfirmNameservers,
}: {
  batchId: string;
  status: WizardStatus | null;
  onComplete: () => void;
  nameserversConfirmed: boolean;
  onConfirmNameservers: () => void;
}) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [autoProgressed, setAutoProgressed] = useState(false);
  const [nsGroups, setNsGroups] = useState<NameserverGroup[]>([]);
  const [nsLoading, setNsLoading] = useState(false);
  const [confirmationChecked, setConfirmationChecked] = useState(false);

  // Auto-fetch nameserver groups if zones already exist (resuming session)
  useEffect(() => {
    if (status && status.zones_created > 0) {
      fetchNameserverGroups();
    }
  }, [batchId, status?.zones_created]);

  const fetchNameserverGroups = async () => {
    try {
      setNsLoading(true);
      const res = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/nameserver-groups`);
      if (res.ok) {
        const data = await res.json();
        console.log("DEBUG Step2Zones: Fetched NS groups:", data.nameserver_groups);
        setNsGroups(data.nameserver_groups || []);
      }
    } catch (e) {
      console.error("Failed to fetch nameserver groups:", e);
    } finally {
      setNsLoading(false);
    }
  };

  const handleCreate = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/step2/create-zones`, {
        method: "POST"
      });
      
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Request failed" }));
        throw new Error(err.detail || "Request failed");
      }
      
      const data = await res.json();
      console.log("DEBUG Step2Zones: Full response:", data);
      setResult(data);
      
      // Check if we can auto-progress to Step 3
      if (data.can_progress) {
        console.log("DEBUG Step2Zones: can_progress=true, auto-advancing to Step 3");
        setAutoProgressed(true);
        // Refresh status which will update current_step
        onComplete();
      } else {
        onComplete(); // Refresh status anyway
      }
    } catch (e) {
      console.error("DEBUG Step2Zones: Error:", e);
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setLoading(false);
    }
  };

  // Determine which NS groups to display:
  // - If we just created zones (result exists), use the result's groups
  // - Otherwise, use the auto-fetched groups (from persistent state)
  const displayNsGroups: NameserverGroup[] = result?.details?.nameserver_groups || nsGroups;
  const multipleGroups = displayNsGroups.length > 1;
  const needsNameserverUpdate = displayNsGroups.length > 0;

  // Check if zones are already created (from a previous session)
  const zonesAlreadyCreated = status && status.zones_created > 0 && status.zones_pending === 0;
  
  // Check if we have existing zones that need verification/continuation
  const hasExistingZones = status && status.zones_created > 0;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900">Step 2: Create Cloudflare Zones</h2>
        <p className="text-gray-600 mt-2">
          {hasExistingZones 
            ? `Verifying ${status?.zones_created} existing zones and configuring DNS records.`
            : `This will create DNS zones and automatically configure redirects for all ${status?.domains_total || 0} domains.`
          }
        </p>
      </div>
      
      {/* Show status summary */}
      {status && (
        <div className="grid grid-cols-3 gap-4 text-center">
          <div className="bg-green-50 p-4 rounded-lg">
            <p className="text-3xl font-bold text-green-600">{status.zones_created}</p>
            <p className="text-sm text-gray-600">Zones Ready</p>
          </div>
          <div className="bg-yellow-50 p-4 rounded-lg">
            <p className="text-3xl font-bold text-yellow-600">{status.zones_pending}</p>
            <p className="text-sm text-gray-600">Pending</p>
          </div>
          <div className="bg-blue-50 p-4 rounded-lg">
            <p className="text-3xl font-bold text-blue-600">{status.redirects_configured}</p>
            <p className="text-sm text-gray-600">Redirects Ready</p>
          </div>
        </div>
      )}
      
      {/* Auto-progressed message */}
      {autoProgressed && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4">
          <p className="text-green-800 font-medium">
            ✅ All zones verified! You can continue to Step 3 once you update nameservers.
          </p>
        </div>
      )}
      
      {!result && !autoProgressed ? (
        <>
          {error && <div className="bg-red-50 border border-red-200 p-4 rounded-lg text-red-800">{error}</div>}
          
          {/* Info box for existing zones */}
          {hasExistingZones && (
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
              <p className="text-blue-800">
                <strong>💡 Existing zones detected!</strong> Click below to verify zones and DNS records. 
                Already configured items will be skipped.
              </p>
            </div>
          )}
          
          <button onClick={handleCreate} disabled={loading}
            className="w-full py-4 bg-blue-600 text-white text-lg font-bold rounded-lg disabled:bg-gray-300 hover:bg-blue-700">
            {loading ? (
              <span className="flex items-center justify-center gap-2">
                <span className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></span>
                {hasExistingZones ? "Verifying Zones & DNS..." : "Creating Zones & Redirects..."} (this may take a few minutes)
              </span>
            ) : hasExistingZones ? (
              "Verify Zones & Configure DNS →"
            ) : (
              "Create Cloudflare Zones →"
            )}
          </button>
        </>
      ) : result ? (
        <div className="space-y-6">
          {/* Success summary */}
          <div className={`border rounded-lg p-4 ${result.success ? 'bg-green-50 border-green-200' : 'bg-yellow-50 border-yellow-200'}`}>
            <p className={`font-medium ${result.success ? 'text-green-800' : 'text-yellow-800'}`}>
              {result.success ? '✅' : '⚠️'} {result.message}
            </p>
            <div className="mt-2 text-sm text-gray-700">
              <p>• Total domains: {result.details?.total || 0}</p>
              {(result.details?.zones_created || 0) > 0 && (
                <p className="text-green-700">• New zones created: {result.details.zones_created}</p>
              )}
              {(result.details?.zones_already_existed || 0) > 0 && (
                <p className="text-blue-700">• Existing zones verified: {result.details.zones_already_existed}</p>
              )}
              {(result.details?.dns_verified || 0) > 0 && (
                <p className="text-green-700">• DNS records verified: {result.details.dns_verified}</p>
              )}
              {(result.details?.redirects_configured || 0) > 0 && (
                <p className="text-green-700">• Redirects configured: {result.details.redirects_configured}</p>
              )}
              {(result.details?.zones_failed || 0) > 0 && (
                <p className="text-red-600">• Zones failed: {result.details.zones_failed}</p>
              )}
            </div>
            
            {/* Show errors if any */}
            {result.details?.errors?.length > 0 && (
              <details className="mt-3">
                <summary className="text-red-600 cursor-pointer text-sm">
                  Show {result.details.errors.length} error(s)
                </summary>
                <ul className="mt-2 text-xs text-red-600 space-y-1">
                  {result.details.errors.map((err: any, i: number) => (
                    <li key={i}>{err.domain}: {err.error}</li>
                  ))}
                </ul>
              </details>
            )}
          </div>

          {/* Nameserver groups */}
          {displayNsGroups.length > 0 && (
            <>
              <div>
                <h3 className="font-bold text-gray-900 mb-2">
                  📋 Update These Nameservers at Porkbun
                </h3>
                <p className="text-sm text-gray-600 mb-4">
                  Copy the nameservers below and update them at your domain registrar.
                  Domains are grouped by their assigned nameservers.
                </p>
                {multipleGroups && (
                  <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3 text-sm text-yellow-800">
                    ⚠️ This batch has {displayNsGroups.length} different nameserver groups. Make sure each
                    domain uses the correct nameserver pair.
                  </div>
                )}
              </div>

              {displayNsGroups.map((g, i) => (
                <div key={i} className="border rounded-lg p-4 bg-gray-50">
                  <div className="flex justify-between items-start">
                    <div className="flex-1">
                      <p className="font-bold text-lg">{g.domain_count} domain{g.domain_count !== 1 ? 's' : ''}</p>
                      <div className="mt-2 space-y-1">
                        <p className="text-sm font-mono bg-white px-2 py-1 rounded border">
                          NS1: {g.nameservers[0] || 'N/A'}
                        </p>
                        <p className="text-sm font-mono bg-white px-2 py-1 rounded border">
                          NS2: {g.nameservers[1] || 'N/A'}
                        </p>
                      </div>
                      <details className="mt-2">
                        <summary className="text-sm text-gray-600 cursor-pointer">Show domains</summary>
                        <ul className="mt-1 text-xs text-gray-500">
                          {g.domains.map((d, j) => (
                            <li key={j}>{d}</li>
                          ))}
                        </ul>
                      </details>
                    </div>
                    <button 
                      onClick={() => {
                        navigator.clipboard.writeText(g.nameservers.join("\n"));
                        alert("Nameservers copied to clipboard!");
                      }}
                      className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
                    >
                      📋 Copy NS
                    </button>
                  </div>
                </div>
              ))}
            </>
          )}

          {displayNsGroups.length === 0 && !result.can_progress && (
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
              <p className="text-yellow-800">
                ⚠️ No nameservers returned. Check the Cloudflare dashboard to verify zones were created.
              </p>
            </div>
          )}

          {/* Next step - show different based on can_progress */}
          {result.can_progress ? (
            <div className="bg-green-50 border border-green-200 rounded-lg p-4">
              <p className="text-green-800">
                <strong>✅ All zones ready!</strong> You can now proceed to Step 3 to monitor nameserver propagation.
              </p>
            </div>
          ) : (
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
              <p className="text-blue-800">
                <strong>Next:</strong> Update nameservers at Porkbun for each group above, 
                then click continue to monitor propagation.
              </p>
            </div>
          )}
          {needsNameserverUpdate && (
            <label className="flex items-start gap-3 bg-gray-50 border border-gray-200 rounded-lg p-4">
              <input
                type="checkbox"
                checked={confirmationChecked}
                onChange={(e) => {
                  setConfirmationChecked(e.target.checked);
                  if (e.target.checked && !nameserversConfirmed) {
                    onConfirmNameservers();
                  }
                }}
                className="mt-1 rounded"
              />
              <span className="text-sm text-gray-700">
                I’ve updated the nameservers at my registrar for <strong>all</strong> domains above.
              </span>
            </label>
          )}

          <button
            onClick={async () => {
              if (!nameserversConfirmed && confirmationChecked) {
                onConfirmNameservers();
              } else {
                await onComplete();
              }
            }}
            disabled={needsNameserverUpdate && !confirmationChecked}
            className={`w-full py-4 text-white text-lg font-bold rounded-lg ${
              result.can_progress
                ? 'bg-green-600 hover:bg-green-700'
                : 'bg-blue-600 hover:bg-blue-700'
            } ${needsNameserverUpdate && !confirmationChecked ? 'opacity-50 cursor-not-allowed' : ''}`}
          >
            {result.can_progress
              ? "Continue to Nameserver Verification →"
              : "I've Updated Nameservers → Continue"
            }
          </button>
        </div>
      ) : null}
    </div>
  );
}

interface AutoRunStatus {
  batch_id: string;
  status: "idle" | "running" | "completed" | "failed" | "stopped";
  current_step: number;
  current_step_name: string;
  progress: {
    step4: { completed: number; failed: number; total: number };
    step5: { completed: number; failed: number; total: number };
    step6: { completed: number; failed: number; total: number };
    step7: { completed: number; failed: number; total: number };
  };
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  message: string;
}

function Step3Propagation({ batchId, status, onComplete, onNext }: { batchId: string; status: WizardStatus | null; onComplete: () => void; onNext: () => void }) {
  const [checking, setChecking] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [continuing, setContinuing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);
  const [autoCheckEnabled, setAutoCheckEnabled] = useState(true);
  const [nsGroups, setNsGroups] = useState<NameserverGroup[]>([]);
  const [nsLoading, setNsLoading] = useState(true);
  

  // Fetch nameserver groups on mount
  useEffect(() => {
    const fetchNsGroups = async () => {
      try {
        setNsLoading(true);
        const res = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/nameserver-groups`);
        if (res.ok) {
          const data = await res.json();
          setNsGroups(data.nameserver_groups || []);
        }
      } catch (e) {
        console.error("Failed to fetch nameserver groups:", e);
      } finally {
        setNsLoading(false);
      }
    };
    fetchNsGroups();
  }, [batchId]);


  // Auto-check every 15 minutes
  useEffect(() => {
    if (!autoCheckEnabled) return;
    
    // Initial check after 60 seconds (give user time to read the page)
    const initialTimeout = setTimeout(() => {
      handleCheck(true);
    }, 60000);

    // Then check every 15 minutes
    const interval = setInterval(() => {
      handleCheck(true);
    }, 15 * 60 * 1000); // 15 minutes

    return () => {
      clearTimeout(initialTimeout);
      clearInterval(interval);
    };
  }, [batchId, autoCheckEnabled]);

  const handleCheck = async (isAutoCheck = false) => {
    if (checking) return;
    setChecking(true);
    setError(null);
    
    try {
      const res = await postStep(batchId, "/step3/check-propagation");
      setLastChecked(new Date());
      onComplete(); // Refresh status
      
      // If auto-advanced, the status will reflect it
      if (res.details?.auto_advanced) {
        // Status refresh will show step 4
        console.log("Auto-advanced to Step 4!");
      }
    } catch (e) {
      if (!isAutoCheck) {
        setError(e instanceof Error ? e.message : "Check failed");
      }
    } finally {
      setChecking(false);
    }
  };

  const handleContinueAnyway = async () => {
    setContinuing(true);
    setError(null);
    try {
      await postStep(batchId, "/step3/continue-anyway");
      onComplete();
      onNext();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to continue");
    } finally {
      setContinuing(false);
    }
  };

  const handleRetryRedirects = async () => {
    setRetrying(true);
    setError(null);
    try {
      await postStep(batchId, "/step3/retry-redirects");
      onComplete();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Retry failed");
    } finally {
      setRetrying(false);
    }
  };

  const allPropagated = status && status.ns_pending === 0 && status.ns_propagated > 0;
  const hasFailedRedirects = status && status.redirects_configured < status.domains_total;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900">Step 3: Waiting for Nameserver Propagation</h2>
        <p className="text-gray-600 mt-2">
          Update nameservers at your registrar (Porkbun), then wait for DNS propagation.
          This typically takes 1-48 hours.
        </p>
      </div>

      {/* Status Grid */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-green-50 rounded-lg p-4 text-center">
          <p className="text-3xl font-bold text-green-600">{status?.ns_propagated || 0}</p>
          <p className="text-sm text-gray-600">Propagated</p>
        </div>
        <div className="bg-yellow-50 rounded-lg p-4 text-center">
          <p className="text-3xl font-bold text-yellow-600">{status?.ns_pending || 0}</p>
          <p className="text-sm text-gray-600">Pending</p>
        </div>
        <div className="bg-blue-50 rounded-lg p-4 text-center">
          <p className="text-3xl font-bold text-blue-600">{status?.redirects_configured || 0}</p>
          <p className="text-sm text-gray-600">Redirects Ready</p>
        </div>
      </div>

      {/* Nameserver Groups Reference */}
      {nsLoading ? (
        <div className="text-center py-4 text-gray-500">Loading nameservers...</div>
      ) : nsGroups.length > 0 && (
        <div className="border rounded-lg p-4 bg-gray-50">
          <h3 className="font-bold text-gray-900 mb-3">📋 Nameservers to Update at Your Registrar</h3>
          {nsGroups.length > 1 && (
            <div className="mb-3 bg-yellow-50 border border-yellow-200 rounded-lg p-2 text-sm text-yellow-800">
              ⚠️ Multiple nameserver groups detected. Make sure each domain uses its assigned pair.
            </div>
          )}
          <div className="space-y-3">
            {nsGroups.map((g, i) => (
              <div key={i} className="bg-white rounded-lg p-3 border">
                <div className="flex justify-between items-start">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="font-medium text-gray-900">
                        {g.domain_count} domain{g.domain_count !== 1 ? 's' : ''}
                      </span>
                      {(g.propagated_count || 0) > 0 && (
                        <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">
                          ✓ {g.propagated_count} propagated
                        </span>
                      )}
                      {(g.pending_count || 0) > 0 && (
                        <span className="text-xs bg-yellow-100 text-yellow-700 px-2 py-0.5 rounded-full">
                          ⏳ {g.pending_count} pending
                        </span>
                      )}
                    </div>
                    <div className="flex gap-2 flex-wrap">
                      <code className="text-xs bg-gray-100 px-2 py-1 rounded">
                        {g.nameservers[0] || 'N/A'}
                      </code>
                      <code className="text-xs bg-gray-100 px-2 py-1 rounded">
                        {g.nameservers[1] || 'N/A'}
                      </code>
                    </div>
                    <details className="mt-2">
                      <summary className="text-xs text-gray-500 cursor-pointer">Show domains</summary>
                      <ul className="mt-1 text-xs text-gray-500 max-h-32 overflow-y-auto">
                        {g.domains.map((d, j) => (
                          <li key={j}>{d}</li>
                        ))}
                      </ul>
                    </details>
                  </div>
                  <button 
                    onClick={() => {
                      navigator.clipboard.writeText(g.nameservers.join("\n"));
                      alert("Nameservers copied!");
                    }}
                    className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700"
                  >
                    📋 Copy
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Auto-check status */}
      <div className="bg-gray-50 rounded-lg p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="font-medium text-gray-900">
              {autoCheckEnabled ? "🔄 Auto-checking every 15 minutes" : "Auto-check disabled"}
            </p>
            {lastChecked && (
              <p className="text-sm text-gray-500">
                Last checked: {lastChecked.toLocaleTimeString()}
              </p>
            )}
          </div>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={autoCheckEnabled}
              onChange={(e) => setAutoCheckEnabled(e.target.checked)}
              className="rounded"
            />
            <span className="text-sm">Auto-check</span>
          </label>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-red-800">{error}</p>
        </div>
      )}

      {/* All propagated message */}
      {allPropagated && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4">
          <p className="text-green-800 font-medium">
            ✅ All nameservers propagated! You can now continue to Step 4.
          </p>
        </div>
      )}

      {/* Manual check button */}
      <button
        onClick={() => handleCheck(false)}
        disabled={checking}
        className="w-full py-3 bg-blue-600 text-white font-bold rounded-lg hover:bg-blue-700 disabled:opacity-50"
      >
        {checking ? (
          <span className="flex items-center justify-center gap-2">
            <span className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></span>
            Checking...
          </span>
        ) : (
          "🔄 Check Propagation Now"
        )}
      </button>

      {/* Retry redirects if some failed */}
      {hasFailedRedirects && (
        <div className="space-y-2">
          <button
            onClick={handleRetryRedirects}
            disabled={retrying}
            className="w-full py-3 border-2 border-orange-500 text-orange-600 font-bold rounded-lg hover:bg-orange-50 disabled:opacity-50"
          >
            {retrying ? (
              <span className="flex items-center justify-center gap-2">
                <span className="animate-spin rounded-full h-5 w-5 border-b-2 border-orange-500"></span>
                Retrying...
              </span>
            ) : (
              `🔁 Retry Failed Redirects (${(status?.domains_total || 0) - (status?.redirects_configured || 0)} pending)`
            )}
          </button>
          <p className="text-xs text-gray-500 text-center">
            💡 Only domains with Cloudflare zones can have redirects configured. 
            If domains failed zone creation in Step 2, go back and retry "Create Zones" first.
          </p>
        </div>
      )}

      {/* Continue options */}
      <div className="border-t pt-6 mt-6">
        {allPropagated ? (
          <button
            onClick={onNext}
            className="w-full py-4 bg-green-600 text-white text-lg font-bold rounded-lg hover:bg-green-700"
          >
            Continue to Tenant Setup →
          </button>
        ) : (
          <div className="space-y-3">
            <p className="text-sm text-gray-600 text-center">
              You can continue to import tenants while waiting for propagation.
            </p>
            <button
              onClick={handleContinueAnyway}
              disabled={continuing}
              className="w-full py-3 border-2 border-gray-300 text-gray-700 font-medium rounded-lg hover:bg-gray-50 disabled:opacity-50"
            >
              {continuing ? "Continuing..." : "Continue Anyway (Skip Waiting) →"}
            </button>
          </div>
        )}
      </div>

      {/* Info box */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 text-sm">
        <p className="text-blue-800">
          <strong>💡 Tip:</strong> Propagation can take up to 48 hours. You can safely continue
          to Step 4 (Import Tenants) while waiting. However, Step 5 (M365 Setup) requires
          nameservers to be fully propagated.
        </p>
      </div>

    </div>
  );
}

interface TenantItem {
  id: string;
  name: string;
  admin_email: string;
  custom_domain: string | null;
  first_login_completed: boolean;
  setup_error: string | null;
  status: string;
}

interface Step4Status {
  tenants_total: number;
  tenants_first_login_complete: number;
  tenants_linked: number;
  tenants_failed: number;
  domains_total: number;
  ready_for_step5: boolean;
}

interface AutomationProgress {
  completed: number;
  failed: number;
  total: number;
}

function Step4Tenants({ batchId, status, onComplete }: { batchId: string; status: WizardStatus | null; onComplete: () => void }) {
  // Import state
  const [tenantCsv, setTenantCsv] = useState<File | null>(null);
  const [credentialsTxt, setCredentialsTxt] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [importResult, setImportResult] = useState<any>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [previewResult, setPreviewResult] = useState<any>(null);
  const csvInputRef = useRef<HTMLInputElement>(null);
  const txtInputRef = useRef<HTMLInputElement>(null);

  // Link state
  const [linking, setLinking] = useState(false);
  const [linkResult, setLinkResult] = useState<any>(null);

  // Automation state
  const [automating, setAutomating] = useState(false);
  const [automationStarted, setAutomationStarted] = useState(false);
  const [progress, setProgress] = useState<AutomationProgress>({ completed: 0, failed: 0, total: 0 });
  const [estimatedMinutes, setEstimatedMinutes] = useState(0);
  const hardcodedPassword = "#Sendemails1";
  const hardcodedMaxWorkers = 2;

  // Step 4 detailed status
  const [step4Status, setStep4Status] = useState<Step4Status | null>(null);
  const [tenants, setTenants] = useState<TenantItem[]>([]);
  const [loadingTenants, setLoadingTenants] = useState(false);

  // Auto-Run state (Auto-Complete Steps 4→7)
  const [autoRunDisplayName, setAutoRunDisplayName] = useState("");
  const [autoRunStarting, setAutoRunStarting] = useState(false);
  const [autoRunStatus, setAutoRunStatus] = useState<AutoRunStatus | null>(null);
  const [autoRunPolling, setAutoRunPolling] = useState(false);
  const [autoRunError, setAutoRunError] = useState<string | null>(null);
  const [autoRunSequencer, setAutoRunSequencer] = useState("instantly");

  const sequencerOptions = [
    { key: "instantly", label: "Instantly.ai" },
    { key: "plusvibe", label: "PlusVibe" },
    { key: "smartlead", label: "Smartlead.ai" },
  ];

  // Fetch step4 status on mount and when needed
  const fetchStep4Status = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/step4/status`);
      if (res.ok) {
        const data = await res.json();
        setStep4Status(data);
      }
    } catch (e) {
      console.error("Failed to fetch step4 status:", e);
    }
  };

  // Fetch tenants list
  const fetchTenants = async () => {
    try {
      setLoadingTenants(true);
      const res = await fetch(`${API_BASE}/api/v1/tenants/?batch_id=${batchId}`);
      if (res.ok) {
        const data = await res.json();
        setTenants(data);
      }
    } catch (e) {
      console.error("Failed to fetch tenants:", e);
    } finally {
      setLoadingTenants(false);
    }
  };

  useEffect(() => {
    fetchStep4Status();
    if (status && status.tenants_total > 0) {
      fetchTenants();
    }
  }, [batchId, status?.tenants_total]);

  useEffect(() => {
    if (status?.sequencer_app_key) {
      setAutoRunSequencer(status.sequencer_app_key);
    }
  }, [status?.sequencer_app_key]);

  // Poll progress during automation
  useEffect(() => {
    if (!automationStarted) return;

    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/step4/progress`);
        if (res.ok) {
          const data = await res.json();
          setProgress(data);

          // Check if automation complete
          if (data.total > 0 && (data.completed + data.failed) >= data.total) {
            setAutomating(false);
            setAutomationStarted(false);
            fetchStep4Status();
            fetchTenants();
            onComplete();
          }
        }
      } catch (e) {
        console.error("Progress poll error:", e);
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [automationStarted, batchId]);

  // Preview tenants
  const handlePreview = async () => {
    if (!tenantCsv || !credentialsTxt) return;
    setPreviewing(true);
    setImportError(null);
    setPreviewResult(null);
    try {
      const formData = new FormData();
      formData.append("tenant_csv", tenantCsv);
      formData.append("credentials_txt", credentialsTxt);
      
      const res = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/step4/preview-tenants`, {
        method: "POST",
        body: formData,
      });
      
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Preview failed" }));
        throw new Error(err.detail || "Preview failed");
      }
      
      const data = await res.json();
      setPreviewResult(data);
    } catch (e) {
      setImportError(e instanceof Error ? e.message : "Preview failed");
    } finally {
      setPreviewing(false);
    }
  };

  // Poll auto-run status when running
  useEffect(() => {
    if (!autoRunPolling) return;

    const pollStatus = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/auto-run/status`);
        if (res.ok) {
          const data = await res.json();
          setAutoRunStatus(data);

          // Stop polling if completed or failed
          if (data.status === "completed" || data.status === "failed" || data.status === "stopped") {
            setAutoRunPolling(false);
            onComplete(); // Refresh main status
          }
        }
      } catch (e) {
        console.error("Failed to poll auto-run status:", e);
      }
    };

    pollStatus(); // Initial poll
    const interval = setInterval(pollStatus, 3000); // Poll every 3 seconds

    return () => clearInterval(interval);
  }, [autoRunPolling, batchId]);

  // Start auto-run (Steps 4→7)
  const handleStartAutoRun = async () => {
    if (!autoRunDisplayName.trim() || !autoRunDisplayName.includes(" ")) {
      setAutoRunError("Please enter a full name (first and last name) for mailbox display names");
      return;
    }

    setAutoRunStarting(true);
    setAutoRunError(null);

    try {
      const res = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/auto-run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          new_password: "#Sendemails1",
          display_name: autoRunDisplayName.trim(),
          sequencer_app_key: autoRunSequencer,
        })
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to start" }));
        throw new Error(err.detail || err.message || "Failed to start auto-run");
      }

      const data = await res.json();
      if (data.success) {
        setAutoRunPolling(true);
        // Fetch initial status
        const statusRes = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/auto-run/status`);
        if (statusRes.ok) {
          setAutoRunStatus(await statusRes.json());
        }
      } else {
        setAutoRunError(data.message || "Failed to start auto-run");
      }
    } catch (e) {
      setAutoRunError(e instanceof Error ? e.message : "Failed to start auto-run");
    } finally {
      setAutoRunStarting(false);
    }
  };

  // Stop auto-run
  const handleStopAutoRun = async () => {
    if (!confirm("Stop the auto-run process? Progress made so far will be preserved.")) return;

    try {
      const res = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/auto-run/stop`, {
        method: "POST"
      });

      if (res.ok) {
        setAutoRunPolling(false);
        onComplete();
      }
    } catch (e) {
      console.error("Failed to stop auto-run:", e);
    }
  };

  // Import tenants
  const handleImport = async () => {
    if (!tenantCsv || !credentialsTxt) return;
    setImporting(true);
    setImportError(null);
    try {
      const formData = new FormData();
      formData.append("tenant_csv", tenantCsv);
      formData.append("credentials_txt", credentialsTxt);
      
      const res = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/step4/import-tenants`, {
        method: "POST",
        body: formData,
      });
      
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Import failed" }));
        throw new Error(err.detail || "Import failed");
      }
      
      const data = await res.json();
      setImportResult(data.details);
      setPreviewResult(null);
      onComplete();
      fetchStep4Status();
      fetchTenants();
    } catch (e) {
      setImportError(e instanceof Error ? e.message : "Import failed");
    } finally {
      setImporting(false);
    }
  };

  // Auto-link domains
  const handleLinkDomains = async () => {
    setLinking(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/step4/link-domains`, {
        method: "POST",
      });
      if (res.ok) {
        const data = await res.json();
        setLinkResult(data.details);
        onComplete();
        fetchStep4Status();
        fetchTenants();
      }
    } catch (e) {
      console.error("Link domains error:", e);
    } finally {
      setLinking(false);
    }
  };

  // Start automation with debouncing to prevent double-clicks
  const automationRequestInProgress = useRef(false);
  
  const handleStartAutomation = async () => {
    // Debouncing: prevent multiple rapid clicks
    if (automationRequestInProgress.current) {
      return;
    }
    
    // Mark request as in-progress immediately
    automationRequestInProgress.current = true;
    setAutomating(true);
    setAutomationStarted(true);
    setProgress({ completed: 0, failed: 0, total: 0 });
    
    try {
      const formData = new FormData();
      formData.append("new_password", hardcodedPassword);
      formData.append("max_workers", hardcodedMaxWorkers.toString());
      
      const res = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/step4/start-automation`, {
        method: "POST",
        body: formData,
      });
      
      if (res.ok) {
        const data = await res.json();
        
        // Check if automation already running (from server-side deduplication)
        if (data.already_running) {
          alert(data.message);
          setAutomating(false);
          setAutomationStarted(false);
          automationRequestInProgress.current = false;
          return;
        }
        
        setProgress(prev => ({ ...prev, total: data.tenants }));
        setEstimatedMinutes(data.estimated_minutes || Math.round(data.tenants / hardcodedMaxWorkers * 1.5));
      } else {
        // Request failed - reset state
        const errorData = await res.json().catch(() => ({ message: "Failed to start" }));
        alert(errorData.message || "Failed to start automation");
        setAutomating(false);
        setAutomationStarted(false);
        automationRequestInProgress.current = false;
      }
    } catch (e) {
      console.error("Start automation error:", e);
      alert(e instanceof Error ? e.message : "Failed to start automation");
      setAutomating(false);
      setAutomationStarted(false);
      automationRequestInProgress.current = false;
    }
  };
  
  // Reset request flag when automation completes (from polling detection)
  useEffect(() => {
    if (!automating && !automationStarted) {
      automationRequestInProgress.current = false;
    }
  }, [automating, automationStarted]);

  // Download templates
  const downloadCsvTemplate = () => {
    const csv = `Company Name,onmicrosoft,Address,Admin Name,Admin Email,Admin Phone,UUID
Example Corp,examplecorp,123 Main St,John Doe,john@gmail.com,+1234567890,12345678-1234-1234-1234-123456789012`;
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "tenants_template.csv";
    a.click();
  };

  const downloadTxtTemplate = () => {
    const txt = `Username\tPassword
admin@example.onmicrosoft.com\tTempP@ss123!`;
    const blob = new Blob([txt], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "credentials_template.txt";
    a.click();
  };

  // Calculate progress percentage
  const progressPercent = progress.total > 0 
    ? Math.round((progress.completed + progress.failed) / progress.total * 100) 
    : 0;
  
  // Estimated time remaining
  const remaining = progress.total - progress.completed - progress.failed;
  const etaMinutes = remaining > 0 ? Math.round(remaining / hardcodedMaxWorkers * 1.5) : 0;

  // Check if all complete
  const allComplete = step4Status && step4Status.tenants_total > 0 && 
    step4Status.tenants_first_login_complete === step4Status.tenants_total;

  // Get status icon for a tenant
  const getStatusIcon = (tenant: TenantItem) => {
    if (tenant.first_login_completed) {
      // Check if it was skipped
      if (tenant.setup_error?.startsWith('SKIPPED:')) {
        return <span className="text-yellow-500" title="Skipped">⏭️</span>;
      }
      return <span className="text-green-500" title="Completed">✅</span>;
    }
    if (tenant.setup_error || tenant.status === "error") {
      return (
        <span className="text-red-500" title={tenant.setup_error || "Automation error"}>
          ❌
        </span>
      );
    }
    if (automating) {
      return <span className="text-yellow-500 animate-pulse" title="Processing">⏳</span>;
    }
    return <span className="text-gray-400" title="Pending">⏳</span>;
  };

  // Skip a single tenant
  const handleSkipTenant = async (tenantId: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/step4/skip-tenant/${tenantId}`, {
        method: "POST"
      });
      if (res.ok) {
        fetchStep4Status();
        fetchTenants();
        onComplete();
      }
    } catch (e) {
      console.error("Skip tenant error:", e);
    }
  };

  // Retry a single tenant
  const handleRetryTenant = async (tenantId: string) => {
    try {
      const formData = new FormData();
      formData.append("new_password", hardcodedPassword);
      
      const res = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/step4/retry-tenant/${tenantId}`, {
        method: "POST",
        body: formData
      });
      if (res.ok) {
        fetchStep4Status();
        fetchTenants();
      }
    } catch (e) {
      console.error("Retry tenant error:", e);
    }
  };

  // Skip all failed tenants
  const handleSkipAllFailed = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/step4/skip-all-failed`, {
        method: "POST"
      });
      if (res.ok) {
        const data = await res.json();
        alert(`Skipped ${data.skipped_count} failed tenant(s)`);
        fetchStep4Status();
        fetchTenants();
        onComplete();
      }
    } catch (e) {
      console.error("Skip all failed error:", e);
    }
  };

  // Get failed tenants (have error but not completed/skipped)
  const failedTenants = tenants.filter(t =>
    (t.setup_error || t.status === "error") &&
    !t.first_login_completed &&
    !t.setup_error?.startsWith('SKIPPED:')
  );

  // Phase 1: Import UI (no tenants yet)
  if (!status || status.tenants_total === 0) {
    return (
      <div className="space-y-6">
        <div>
          <h2 className="text-xl font-bold text-gray-900">Step 4: Import Tenants</h2>
          <p className="text-gray-600 mt-2">
            Upload your M365 tenant list CSV and credentials TXT file from your reseller.
          </p>
        </div>

        {/* File Upload Section */}
        <div className="grid grid-cols-2 gap-4">
          {/* Tenant CSV */}
          <div 
            className="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center hover:border-blue-500 cursor-pointer"
            onClick={() => csvInputRef.current?.click()}
          >
            <input 
              type="file" 
              ref={csvInputRef} 
              className="hidden" 
              accept=".csv" 
              onChange={(e) => setTenantCsv(e.target.files?.[0] || null)} 
            />
            <div className="text-4xl mb-2">📋</div>
            <p className="font-medium">{tenantCsv ? tenantCsv.name : "Tenant List CSV"}</p>
            <p className="text-xs text-gray-500 mt-1">Company info, Tenant IDs</p>
            <button 
              type="button" 
              onClick={(e) => { e.stopPropagation(); downloadCsvTemplate(); }}
              className="mt-2 text-sm text-blue-600 underline"
            >
              Download Template
            </button>
          </div>

          {/* Credentials TXT */}
          <div 
            className="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center hover:border-blue-500 cursor-pointer"
            onClick={() => txtInputRef.current?.click()}
          >
            <input 
              type="file" 
              ref={txtInputRef} 
              className="hidden" 
              accept=".txt" 
              onChange={(e) => setCredentialsTxt(e.target.files?.[0] || null)} 
            />
            <div className="text-4xl mb-2">🔐</div>
            <p className="font-medium">{credentialsTxt ? credentialsTxt.name : "Credentials TXT"}</p>
            <p className="text-xs text-gray-500 mt-1">Admin emails + passwords</p>
            <button 
              type="button" 
              onClick={(e) => { e.stopPropagation(); downloadTxtTemplate(); }}
              className="mt-2 text-sm text-blue-600 underline"
            >
              Download Template
            </button>
          </div>
        </div>

        {/* Import Error */}
        {importError && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4">
            <p className="text-red-800">{importError}</p>
          </div>
        )}

        {/* Preview Results */}
        {previewResult && (
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 space-y-3">
            <div className="flex justify-between items-center">
              <h3 className="font-bold text-blue-900">Preview Results</h3>
              <button onClick={() => setPreviewResult(null)} className="text-blue-600 hover:text-blue-800 text-sm">✕ Close</button>
            </div>
            
            <div className="grid grid-cols-2 gap-4">
              <div className="bg-green-100 rounded-lg p-3 text-center">
                <p className="text-2xl font-bold text-green-700">{previewResult.new_count}</p>
                <p className="text-xs text-green-600">New Tenants</p>
              </div>
              <div className="bg-gray-100 rounded-lg p-3 text-center">
                <p className="text-2xl font-bold text-gray-700">{previewResult.existing_count}</p>
                <p className="text-xs text-gray-600">Already Exist</p>
              </div>
            </div>

            {previewResult.new_tenants && previewResult.new_tenants.length > 0 && (
              <details className="text-sm">
                <summary className="cursor-pointer text-green-700 font-medium">
                  Show {previewResult.new_count} new tenant(s)
                </summary>
                <ul className="mt-2 ml-4 space-y-1 text-green-600 max-h-32 overflow-y-auto">
                  {previewResult.new_tenants.map((tenant: any, i: number) => (
                    <li key={i} className="text-xs">• {tenant.name} ({tenant.onmicrosoft_domain})</li>
                  ))}
                </ul>
              </details>
            )}

            {previewResult.existing_tenants && previewResult.existing_tenants.length > 0 && (
              <details className="text-sm">
                <summary className="cursor-pointer text-gray-700 font-medium">
                  Show {previewResult.existing_count} existing tenant(s)
                </summary>
                <ul className="mt-2 ml-4 space-y-1 text-gray-500 max-h-32 overflow-y-auto">
                  {previewResult.existing_tenants.map((item: any, i: number) => (
                    <li key={i} className="text-xs">
                      • {item.name} ({item.onmicrosoft_domain}) <span className="text-gray-400">(Batch: {item.batch_name}, Status: {item.status})</span>
                    </li>
                  ))}
                </ul>
              </details>
            )}

            {previewResult.new_count === 0 && (
              <p className="text-yellow-700 text-sm">⚠️ All tenants already exist in the system. Nothing new to import.</p>
            )}
          </div>
        )}

        {/* Import Results */}
        {importResult && (
          <div className="bg-green-50 border border-green-200 rounded-lg p-4">
            <p className="text-green-800 font-medium">✅ Import Successful!</p>
            <div className="mt-2 text-sm text-green-700">
              <p>• Imported: {importResult.imported} tenants (of {importResult.domains_needing_tenants} needed)</p>
              <p>• Skipped (duplicates): {importResult.skipped_duplicate}</p>
              {importResult.skipped_not_needed > 0 && (
                <p className="text-blue-600">• Skipped (not needed): {importResult.skipped_not_needed}</p>
              )}
              {importResult.missing_password > 0 && (
                <p className="text-orange-600">• Missing passwords: {importResult.missing_password}</p>
              )}
            </div>
          </div>
        )}

        {/* Action Buttons */}
        {!previewResult ? (
          <div className="grid grid-cols-2 gap-4">
            <button 
              onClick={handlePreview}
              disabled={!tenantCsv || !credentialsTxt || previewing}
              className="py-4 bg-gray-600 text-white text-lg font-bold rounded-lg hover:bg-gray-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
            >
              {previewing ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></span>
                  Previewing...
                </span>
              ) : (
                "Preview Tenants"
              )}
            </button>
            <button 
              onClick={handleImport} 
              disabled={!tenantCsv || !credentialsTxt || importing}
              className="py-4 bg-blue-600 text-white text-lg font-bold rounded-lg hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
            >
              {importing ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></span>
                  Importing...
                </span>
              ) : (
                "Import Tenants →"
              )}
            </button>
          </div>
        ) : (
          <button 
            onClick={handleImport}
            disabled={!tenantCsv || !credentialsTxt || importing || previewResult.new_count === 0}
            className="w-full py-4 bg-green-600 text-white text-lg font-bold rounded-lg hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
          >
            {importing ? (
              <span className="flex items-center justify-center gap-2">
                <span className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></span>
                Importing...
              </span>
            ) : (
              `Import ${previewResult.new_count} New Tenant(s) →`
            )}
          </button>
        )}

        {/* Display Name for Mailboxes */}
        <div className="bg-gradient-to-r from-purple-50 to-pink-50 border-2 border-purple-200 rounded-lg p-6 space-y-4">
          <h3 className="text-lg font-bold text-purple-900">Display Name for Mailboxes</h3>
          <p className="text-sm text-purple-700">
            Enter the display name to use for all mailboxes. This is required for auto-complete.
          </p>
          <div>
            <input
              type="text"
              value={autoRunDisplayName}
              onChange={(e) => setAutoRunDisplayName(e.target.value)}
              placeholder="e.g., Ryan Chen"
              className="w-full px-4 py-2 border rounded-lg"
            />
            <p className="text-xs text-gray-500 mt-1">
              Full name (first and last) used for all mailbox display names
            </p>
          </div>
        </div>

        {/* Info */}
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 text-sm">
          <p className="text-blue-800">
            <strong>💡 File Formats:</strong>
          </p>
          <ul className="mt-2 text-blue-700 list-disc list-inside space-y-1">
            <li><strong>CSV:</strong> Company Name, onmicrosoft, Address, Admin Name, Admin Email, Admin Phone, UUID</li>
            <li><strong>TXT:</strong> Tab-separated: Username (tab) Password</li>
          </ul>
        </div>
      </div>
    );
  }

  // Phase 2: Tenants imported - show management UI
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900">Step 4: Tenant Setup</h2>
        <p className="text-gray-600 mt-2">
          Link domains and run first-login automation for all tenants.
        </p>
      </div>

      {/* Status Summary */}
      <div className="grid grid-cols-4 gap-4">
        <div className="bg-blue-50 rounded-lg p-4 text-center">
          <p className="text-3xl font-bold text-blue-600">{status?.tenants_total || 0}</p>
          <p className="text-sm text-gray-600">Total Tenants</p>
        </div>
        <div className="bg-purple-50 rounded-lg p-4 text-center">
          <p className="text-3xl font-bold text-purple-600">{status?.tenants_linked || 0}</p>
          <p className="text-sm text-gray-600">Linked to Domains</p>
        </div>
        <div className="bg-green-50 rounded-lg p-4 text-center">
          <p className="text-3xl font-bold text-green-600">{step4Status?.tenants_first_login_complete || 0}</p>
          <p className="text-sm text-gray-600">First Login Done</p>
        </div>
        <div className="bg-gray-50 rounded-lg p-4 text-center">
          <p className="text-3xl font-bold text-gray-600">{status?.domains_total || 0}</p>
          <p className="text-sm text-gray-600">Available Domains</p>
        </div>
      </div>

      {/* Auto Link Section */}
      {status && status.tenants_linked < status.tenants_total && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="font-medium text-yellow-800">
                ⚠️ {status.tenants_total - status.tenants_linked} tenants need domains linked
              </p>
              <p className="text-sm text-yellow-700 mt-1">
                Auto-link will assign available domains to tenants in order.
              </p>
            </div>
            <button
              onClick={handleLinkDomains}
              disabled={linking}
              className="px-4 py-2 bg-yellow-600 text-white font-bold rounded-lg hover:bg-yellow-700 disabled:opacity-50"
            >
              {linking ? "Linking..." : "🔗 Auto Link Domains"}
            </button>
          </div>
          {linkResult && (
            <p className="mt-2 text-sm text-green-700">
              ✅ Linked {linkResult.linked} tenants to domains
            </p>
          )}
        </div>
      )}

      {/* Automation Section */}
      {!allComplete && (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 space-y-4">
          <h3 className="font-bold text-gray-900">🤖 First-Login Automation</h3>
          <p className="text-sm text-gray-600">
            Automates password change, MFA enrollment (TOTP), and Security Defaults disable.
          </p>

          {!automating && !automationStarted && (
            <div className="text-sm text-gray-500">
              Estimated time: ~{Math.round((status?.tenants_total || 0) / hardcodedMaxWorkers * 1.5)} minutes
              ({status?.tenants_total} tenants × 1.5 min / {hardcodedMaxWorkers} workers)
            </div>
          )}

          <button
            onClick={handleStartAutomation}
            disabled={automating || status?.tenants_linked === 0}
            className="w-full py-3 bg-green-600 text-white font-bold rounded-lg hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
          >
            {automating ? (
              <span className="flex items-center justify-center gap-2">
                <span className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></span>
                Automation Running...
              </span>
            ) : (
              "🚀 Start Automation"
            )}
          </button>
        </div>
      )}

      {/* Progress Bar */}
      {automationStarted && progress.total > 0 && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 space-y-3">
          <div className="flex justify-between items-center">
            <h3 className="font-bold text-blue-900">Automation Progress</h3>
            <span className="text-blue-700 font-mono">{progressPercent}%</span>
          </div>
          
          {/* Progress bar */}
          <div className="w-full bg-gray-200 rounded-full h-4 overflow-hidden">
            <div 
              className="h-full rounded-full transition-all duration-500 flex"
              style={{ width: `${progressPercent}%` }}
            >
              <div 
                className="bg-green-500 h-full" 
                style={{ width: progress.total > 0 ? `${(progress.completed / (progress.completed + progress.failed || 1)) * 100}%` : '100%' }}
              />
              <div 
                className="bg-red-500 h-full" 
                style={{ width: progress.total > 0 ? `${(progress.failed / (progress.completed + progress.failed || 1)) * 100}%` : '0%' }}
              />
            </div>
          </div>

          {/* Stats */}
          <div className="flex justify-between text-sm">
            <span className="text-green-700">✅ {progress.completed} completed</span>
            <span className="text-red-700">❌ {progress.failed} failed</span>
            <span className="text-gray-600">⏳ {remaining} remaining</span>
          </div>

          {remaining > 0 && (
            <p className="text-sm text-blue-700">
              Estimated time remaining: ~{etaMinutes} minute{etaMinutes !== 1 ? 's' : ''}
            </p>
          )}
        </div>
      )}

      {/* Failed Tenants Banner */}
      {failedTenants.length > 0 && !automating && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="font-medium text-yellow-800">
                ⚠️ {failedTenants.length} tenant(s) failed automation
              </p>
              <p className="text-sm text-yellow-700 mt-1">
                You can skip failed tenants to continue, or retry them individually.
              </p>
            </div>
            <button
              onClick={handleSkipAllFailed}
              className="px-4 py-2 bg-yellow-600 text-white font-bold rounded-lg hover:bg-yellow-700"
            >
              Skip All Failed
            </button>
          </div>
        </div>
      )}

      {/* Tenant List */}
      <div className="border rounded-lg overflow-hidden">
        <div className="bg-gray-100 px-4 py-2 border-b flex justify-between items-center">
          <h3 className="font-bold text-gray-900">Tenants</h3>
          <button 
            onClick={fetchTenants} 
            disabled={loadingTenants}
            className="text-sm text-blue-600 hover:underline"
          >
            {loadingTenants ? "Loading..." : "🔄 Refresh"}
          </button>
        </div>
        
        <div className="max-h-96 overflow-y-auto">
          {tenants.length === 0 ? (
            <div className="p-4 text-center text-gray-500">
              {loadingTenants ? "Loading tenants..." : "No tenants found"}
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-gray-50 sticky top-0">
                <tr>
                  <th className="px-3 py-2 text-left w-12">Status</th>
                  <th className="px-3 py-2 text-left">Tenant Name</th>
                  <th className="px-3 py-2 text-left">Admin Email</th>
                  <th className="px-3 py-2 text-left">Domain</th>
                  <th className="px-3 py-2 text-left">Error</th>
                  <th className="px-3 py-2 text-left w-28">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {tenants.map((tenant) => {
                  const hasFailed =
                    (tenant.setup_error || tenant.status === "error") &&
                    !tenant.first_login_completed;
                  const isSkipped = tenant.setup_error?.startsWith('SKIPPED:');
                  const errorMessage = tenant.setup_error || (tenant.status === "error" ? "Automation error" : null);
                  
                  return (
                    <tr 
                      key={tenant.id} 
                      className={`
                        hover:bg-gray-50
                        ${hasFailed ? 'bg-red-50' : ''}
                        ${isSkipped ? 'bg-yellow-50' : ''}
                      `}
                    >
                      <td className="px-3 py-2 text-center">{getStatusIcon(tenant)}</td>
                      <td className="px-3 py-2 font-medium truncate max-w-[140px]" title={tenant.name}>
                        {tenant.name}
                      </td>
                      <td className="px-3 py-2 text-gray-600 font-mono text-xs truncate max-w-[160px]" title={tenant.admin_email}>
                        {tenant.admin_email}
                      </td>
                      <td className="px-3 py-2">
                        {tenant.custom_domain ? (
                          <span className="text-green-600 text-xs">{tenant.custom_domain}</span>
                        ) : (
                          <span className="text-gray-400 text-xs">Not linked</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-xs max-w-[180px]">
                        {errorMessage ? (
                          <span 
                            className={`truncate block ${isSkipped ? 'text-yellow-600' : 'text-red-600'}`}
                            title={errorMessage}
                          >
                            {errorMessage}
                          </span>
                        ) : (
                          <span className="text-gray-400">-</span>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        {hasFailed && !isSkipped && (
                          <div className="flex gap-1">
                            <button
                              onClick={() => handleSkipTenant(tenant.id)}
                              className="px-2 py-1 text-xs bg-gray-200 hover:bg-gray-300 rounded"
                              title="Skip this tenant"
                            >
                              Skip
                            </button>
                            <button
                              onClick={() => handleRetryTenant(tenant.id)}
                              className="px-2 py-1 text-xs bg-blue-500 hover:bg-blue-600 text-white rounded"
                              title="Retry this tenant"
                            >
                              Retry
                            </button>
                          </div>
                        )}
                        {isSkipped && (
                          <span className="text-xs text-yellow-600">Skipped</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Status Legend */}
      <div className="flex flex-wrap gap-4 text-sm text-gray-600">
        <span>⏳ Pending</span>
        <span>✅ Completed</span>
        <span>❌ Failed</span>
        <span>⏭️ Skipped</span>
      </div>

      {/* Auto-Run Progress Display */}
      {autoRunStatus && autoRunStatus.status === "running" && (
        <div className="bg-purple-50 border-2 border-purple-300 rounded-lg p-6 space-y-4">
          <div className="flex justify-between items-center">
            <h3 className="text-lg font-bold text-purple-900">🤖 Auto-Run in Progress</h3>
            <button
              onClick={handleStopAutoRun}
              className="px-4 py-2 bg-red-500 text-white rounded-lg hover:bg-red-600 text-sm font-medium"
            >
              ⏹ Stop
            </button>
          </div>

          <div className="text-purple-800">
            <p className="font-medium">Currently on: Step {autoRunStatus.current_step} - {autoRunStatus.current_step_name}</p>
            <p className="text-sm mt-1">{autoRunStatus.message}</p>
          </div>

          {/* Progress for each step */}
          <div className="grid grid-cols-4 gap-3">
            {[4, 5, 6, 7].map((step) => {
              const stepKey = `step${step}` as keyof typeof autoRunStatus.progress;
              const stepProgress = autoRunStatus.progress[stepKey];
              const total = stepProgress.total || 0;
              const done = stepProgress.completed + stepProgress.failed;
              const percent = total > 0 ? Math.round((done / total) * 100) : 0;
              const isCurrentStep = autoRunStatus.current_step === step;

              return (
                <div
                  key={step}
                  className={`p-3 rounded-lg ${
                    isCurrentStep ? 'bg-purple-200 ring-2 ring-purple-400' : 'bg-purple-100'
                  }`}
                >
                  <p className="text-xs text-purple-600 font-medium">Step {step}</p>
                  <p className="text-lg font-bold text-purple-800">{percent}%</p>
                  <div className="h-1.5 bg-purple-200 rounded-full mt-1 overflow-hidden">
                    <div
                      className="h-full bg-purple-500 transition-all duration-500"
                      style={{ width: `${percent}%` }}
                    />
                  </div>
                  <p className="text-xs text-purple-600 mt-1">
                    {stepProgress.completed}✓ / {stepProgress.failed}✗
                  </p>
                </div>
              );
            })}
          </div>

          {autoRunStatus.started_at && (
            <p className="text-xs text-purple-600">
              Started: {new Date(autoRunStatus.started_at).toLocaleTimeString()}
            </p>
          )}
        </div>
      )}

      {/* Auto-Run Completed Message */}
      {autoRunStatus && (autoRunStatus.status === "completed" || autoRunStatus.status === "failed" || autoRunStatus.status === "stopped") && (
        <div className={`border rounded-lg p-4 ${
          autoRunStatus.status === "completed" ? 'bg-green-50 border-green-200' :
          autoRunStatus.status === "stopped" ? 'bg-yellow-50 border-yellow-200' :
          'bg-red-50 border-red-200'
        }`}>
          <p className={`font-medium ${
            autoRunStatus.status === "completed" ? 'text-green-800' :
            autoRunStatus.status === "stopped" ? 'text-yellow-800' :
            'text-red-800'
          }`}>
            {autoRunStatus.status === "completed" && '✅ Auto-run completed successfully!'}
            {autoRunStatus.status === "stopped" && '⏹ Auto-run was stopped'}
            {autoRunStatus.status === "failed" && `❌ Auto-run failed: ${autoRunStatus.error || 'Unknown error'}`}
          </p>
          <p className="text-sm text-gray-600 mt-1">{autoRunStatus.message}</p>
          {autoRunStatus.completed_at && (
            <p className="text-xs text-gray-500 mt-2">
              Completed: {new Date(autoRunStatus.completed_at).toLocaleString()}
            </p>
          )}
        </div>
      )}

      {/* Auto-Complete All Steps Button - Only show when not running */}
      {!autoRunPolling && (
        <div className="border-t pt-6 mt-6">
          <div className="bg-gradient-to-r from-purple-50 to-pink-50 border-2 border-purple-200 rounded-lg p-6 space-y-4">
            <h3 className="text-lg font-bold text-purple-900 mb-2">🚀 Auto-Complete Remaining Steps</h3>
            <p className="text-sm text-purple-700">
              Enter the display name for mailboxes, then click auto-complete to run Steps 4 through 7
              with auto-retry for failures (up to 4 retries per item).
            </p>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Display Name for Mailboxes *
              </label>
              <input
                type="text"
                value={autoRunDisplayName}
                onChange={(e) => setAutoRunDisplayName(e.target.value)}
                placeholder="e.g., Ryan Chen"
                className="w-full px-4 py-2 border rounded-lg"
              />
              <p className="text-xs text-gray-500 mt-1">
                Full name (first and last) used for all mailbox display names
              </p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Sequencer for Step 7 *
              </label>
              <select
                value={autoRunSequencer}
                onChange={(e) => setAutoRunSequencer(e.target.value)}
                className="w-full px-4 py-2 border rounded-lg bg-white"
              >
                {sequencerOptions.map((opt) => (
                  <option key={opt.key} value={opt.key}>
                    {opt.label}
                  </option>
                ))}
              </select>
              <p className="text-xs text-gray-500 mt-1">
                This determines which app receives admin consent in Step 7.
              </p>
            </div>

            {autoRunError && (
              <div className="bg-red-50 border border-red-200 rounded-lg p-3">
                <p className="text-red-800 text-sm">{autoRunError}</p>
              </div>
            )}

            <button
              onClick={handleStartAutoRun}
              disabled={autoRunStarting || !autoRunDisplayName.includes(" ")}
              className="w-full py-4 bg-gradient-to-r from-purple-600 to-pink-600 text-white text-lg font-bold rounded-lg hover:from-purple-700 hover:to-pink-700 transition-all shadow-lg disabled:from-gray-400 disabled:to-gray-400 disabled:cursor-not-allowed"
            >
              {autoRunStarting ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="animate-spin">⏳</span>
                  Starting...
                </span>
              ) : (
                "🤖 Start Auto-Complete (Steps 4→7)"
              )}
            </button>
          </div>
        </div>
      )}

      {/* Continue Button */}
      <div className="border-t pt-6">
        {allComplete ? (
          <button
            onClick={async () => {
              // Call advance API to move to step 5
              await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/advance`, {
                method: 'POST'
              });
              // Refresh status - this will update activeStep to 5
              onComplete();
            }}
            className="w-full py-4 bg-green-600 text-white text-lg font-bold rounded-lg hover:bg-green-700"
          >
            ✅ All Tenants Ready - Continue to Email Setup →
          </button>
        ) : (
          <div className="space-y-3">
            <p className="text-sm text-gray-600 text-center">
              Complete first-login automation for all tenants before continuing.
            </p>
            <button
              disabled
              className="w-full py-4 bg-gray-300 text-gray-500 text-lg font-bold rounded-lg cursor-not-allowed"
            >
              Continue to Email Setup →
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

interface Step5Status {
  total: number;
  not_started: number;
  domain_added: number;
  domain_verified: number;
  dns_configured: number;
  dkim_cnames_added: number;
  dkim_enabled: number;
  errored: number;
  ready_for_step6: boolean;
  tenants: Array<{
    id: string;
    name: string;
    domain: string | null;
    status: string;
    domain_added: boolean;
    domain_verified: boolean;
    dns_configured: boolean;
    dkim_cnames_added: boolean;
    dkim_enabled: boolean;
    error: string | null;
  }>;
}

interface AutomationStatus {
  status: string;
  total?: number;
  completed?: number;
  successful?: number;
  failed?: number;
  current_tenant?: string;
  current_step?: string;
  error?: string;
  started_at?: string;
  completed_at?: string;
  active_domains?: number;
  tenant_live_progress?: Array<{
    tenant_id: string;
    tenant_name: string;
    domain: string;
    live_step: string;
    live_status: string;
    live_details: string;
    active: boolean;
    timestamp?: number;
  }>;
}

function Step5M365({ batchId, status, onComplete, onNext }: { batchId: string; status: WizardStatus | null; onComplete: () => void; onNext: () => void }) {
  const [automating, setAutomating] = useState(false);
  const [automationStatus, setAutomationStatus] = useState<AutomationStatus | null>(null);
  const [step5Status, setStep5Status] = useState<Step5Status | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isMounted, setIsMounted] = useState(true);

  // Fetch Step 5 detailed status - robust error handling
  const fetchStep5Status = async (signal?: AbortSignal): Promise<boolean> => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/step5/status`, { signal });
      if (!res.ok) {
        // Non-2xx response - log but don't throw
        console.warn(`Step5 status returned ${res.status}`);
        return false;
      }
      const data = await res.json();
      if (isMounted) {
        setStep5Status(data);
      }
      return true;
    } catch (e) {
      // AbortError is expected when cleaning up - don't log
      if (e instanceof Error && e.name === 'AbortError') return false;
      // Other errors - warn but don't throw
      console.warn("Step5 status fetch issue:", e instanceof Error ? e.message : "Unknown");
      return false;
    }
  };

  // Fetch automation status - robust error handling
  const fetchAutomationStatus = async (signal?: AbortSignal): Promise<AutomationStatus | null> => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/step5/automation-status`, { signal });
      if (!res.ok) {
        // Non-2xx - return null, don't throw
        return null;
      }
      const data = await res.json();
      if (isMounted) {
        setAutomationStatus(data);
      }
      return data;
    } catch (e) {
      // AbortError is expected - ignore
      if (e instanceof Error && e.name === 'AbortError') return null;
      // Network errors - return null, don't throw
      return null;
    }
  };

  // Cleanup on unmount
  useEffect(() => {
    setIsMounted(true);
    return () => setIsMounted(false);
  }, []);

  // Initial load
  useEffect(() => {
    const controller = new AbortController();
    
    // Stagger initial fetches to avoid race conditions
    fetchStep5Status(controller.signal);
    setTimeout(() => fetchAutomationStatus(controller.signal), 500);
    
    return () => controller.abort();
  }, [batchId]);

  // Poll automation status AND tenant status while running (for real-time UI updates)
  useEffect(() => {
    if (!automating) return;

    const controller = new AbortController();
    
    const poll = async () => {
      // Stagger fetches - automation status first, then tenant status 1s later
      const autoStatus = await fetchAutomationStatus(controller.signal);
      
      // Wait 1s before fetching tenant status to avoid DB contention
      await new Promise(resolve => setTimeout(resolve, 1000));
      
      if (!controller.signal.aborted) {
        await fetchStep5Status(controller.signal);  // Updates Add/Ver/DNS/DKIM columns
      }
      
      // Check if automation finished
      if (autoStatus && (autoStatus.status === "completed" || autoStatus.status === "error")) {
        setAutomating(false);
        onComplete();
      }
    };
    
    // Run immediately, then every 5s (increased from 3s to reduce DB load)
    poll();
    const interval = setInterval(poll, 5000);

    return () => {
      controller.abort();
      clearInterval(interval);
    };
  }, [automating, batchId]);

  // Start automation
  const handleStartAutomation = async () => {
    setLoading(true);
    setError(null);
    
    try {
      const res = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/step5/start-automation`, {
        method: "POST"
      });
      
      if (!res.ok) {
        const err = await res.json().catch(() => ({ message: "Failed to start automation" }));
        throw new Error(err.message || err.detail || "Failed to start");
      }
      
      const data = await res.json();
      
      if (data.success) {
        setAutomating(true);
        setAutomationStatus({
          status: "running",
          total: data.total_tenants,
          completed: 0,
          successful: 0,
          failed: 0
        });
      } else {
        setError(data.message);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start automation");
    } finally {
      setLoading(false);
    }
  };

  // Retry failed tenants
  const handleRetryFailed = async () => {
    setLoading(true);
    setError(null);
    
    try {
      const res = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/step5/retry-failed`, {
        method: "POST"
      });
      
      if (res.ok) {
        setAutomating(true);
        fetchAutomationStatus();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to retry");
    } finally {
      setLoading(false);
    }
  };

  // Get status icon for tenant
  const getStatusIcon = (tenant: Step5Status['tenants'][0]) => {
    if (tenant.error) return <span title={tenant.error}>🔴</span>;
    if (tenant.dkim_enabled) return <span title="Complete">🟢</span>;
    if (tenant.dkim_cnames_added) return <span title="DKIM CNAMEs added">🟡</span>;
    if (tenant.dns_configured) return <span title="DNS configured">🟡</span>;
    if (tenant.domain_verified) return <span title="Domain verified">🟡</span>;
    if (tenant.domain_added) return <span title="Domain added">🟡</span>;
    return <span title="Not started">⚪</span>;
  };

  // Calculate progress
  const progressPercent = automationStatus?.total 
    ? Math.round(((automationStatus.completed || 0) / automationStatus.total) * 100)
    : 0;

  const allComplete = step5Status && step5Status.ready_for_step6;
  const hasErrors = step5Status && step5Status.errored > 0;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900">Step 5: M365 Domain & DKIM Setup</h2>
        <p className="text-gray-600 mt-2">
          Automatically add domains to M365, configure DNS records, and enable DKIM signing.
        </p>
      </div>

      {/* Status Summary */}
      <div className="grid grid-cols-4 gap-3">
        <div className="bg-gray-50 rounded-lg p-3 text-center">
          <p className="text-2xl font-bold text-gray-600">{step5Status?.not_started || 0}</p>
          <p className="text-xs text-gray-500">Not Started</p>
        </div>
        <div className="bg-blue-50 rounded-lg p-3 text-center">
          <p className="text-2xl font-bold text-blue-600">{step5Status?.domain_verified || 0}</p>
          <p className="text-xs text-gray-500">Verified</p>
        </div>
        <div className="bg-green-50 rounded-lg p-3 text-center">
          <p className="text-2xl font-bold text-green-600">{step5Status?.dkim_enabled || 0}</p>
          <p className="text-xs text-gray-500">DKIM Enabled</p>
        </div>
        <div className="bg-red-50 rounded-lg p-3 text-center">
          <p className="text-2xl font-bold text-red-600">{step5Status?.errored || 0}</p>
          <p className="text-xs text-gray-500">Errors</p>
        </div>
      </div>

      {/* Automation Progress */}
      {automating && automationStatus && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 space-y-3">
          <div className="flex justify-between items-center">
            <h3 className="font-bold text-blue-900">🤖 Automation Running</h3>
            <span className="text-blue-700 font-mono">{progressPercent}%</span>
          </div>
          
          {/* Progress bar */}
          <div className="w-full bg-gray-200 rounded-full h-3 overflow-hidden">
            <div 
              className="h-full bg-blue-500 transition-all duration-500"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
          
          {/* Stats */}
          <div className="flex justify-between text-sm">
            <span className="text-gray-600">
              {automationStatus.completed || 0} / {automationStatus.total || 0} tenants
            </span>
            {automationStatus.current_step && (
              <span className="text-blue-700">{automationStatus.current_step}</span>
            )}
          </div>
          
          {automationStatus.successful !== undefined && (
            <div className="flex gap-4 text-sm">
              <span className="text-green-700">✅ {automationStatus.successful} successful</span>
              <span className="text-red-700">❌ {automationStatus.failed || 0} failed</span>
            </div>
          )}
        </div>
      )}

      {/* Completed Message */}
      {automationStatus?.status === "completed" && !automating && (
        <div className={`border rounded-lg p-4 ${
          automationStatus.failed === 0 ? 'bg-green-50 border-green-200' : 'bg-yellow-50 border-yellow-200'
        }`}>
          <p className={`font-medium ${
            automationStatus.failed === 0 ? 'text-green-800' : 'text-yellow-800'
          }`}>
            {automationStatus.failed === 0 
              ? '✅ Automation completed successfully!'
              : `⚠️ Automation completed with ${automationStatus.failed} errors`
            }
          </p>
          <p className="text-sm text-gray-600 mt-1">
            {automationStatus.successful} tenants configured, {automationStatus.failed || 0} failed
          </p>
        </div>
      )}

      {/* Error Message */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-red-800">{error}</p>
        </div>
      )}

      {/* Action Buttons */}
      {!automating && (
        <div className="space-y-3">
          {!allComplete && (
            <button
              onClick={handleStartAutomation}
              disabled={loading || (step5Status?.total === 0)}
              className="w-full py-4 bg-blue-600 text-white text-lg font-bold rounded-lg hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
            >
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></span>
                  Starting...
                </span>
              ) : (
                `🚀 Start Automation (${step5Status?.total || 0} tenants)`
              )}
            </button>
          )}

          {hasErrors && (
            <button
              onClick={handleRetryFailed}
              disabled={loading}
              className="w-full py-3 border-2 border-orange-500 text-orange-600 font-bold rounded-lg hover:bg-orange-50 disabled:opacity-50"
            >
              🔁 Retry Failed Tenants ({step5Status?.errored || 0})
            </button>
          )}
        </div>
      )}

      {/* Tenant List */}
      {step5Status && step5Status.tenants.length > 0 && (
        <div className="border rounded-lg overflow-hidden">
          <div className="bg-gray-100 px-4 py-2 border-b flex justify-between items-center">
            <h3 className="font-bold text-gray-900">Tenant Status</h3>
            <button 
              onClick={() => fetchStep5Status()}
              className="text-sm text-blue-600 hover:underline"
            >
              🔄 Refresh
            </button>
          </div>
          
          <div className="max-h-64 overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 sticky top-0">
                <tr>
                  <th className="px-3 py-2 text-left w-10">St</th>
                  <th className="px-3 py-2 text-left">Tenant</th>
                  <th className="px-3 py-2 text-left">Domain</th>
                  <th className="px-3 py-2 text-center">Add</th>
                  <th className="px-3 py-2 text-center">Ver</th>
                  <th className="px-3 py-2 text-center">DNS</th>
                  <th className="px-3 py-2 text-center">DKIM</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {step5Status.tenants.map((tenant) => {
                  // Find live progress for this tenant's domain
                  const liveProgress = automationStatus?.tenant_live_progress?.find(
                    p => p.domain === tenant.domain || p.tenant_id === tenant.id
                  );
                  const isActive = liveProgress?.active;
                  
                  return (
                    <tr key={tenant.id} className={`hover:bg-gray-50 ${tenant.error ? 'bg-red-50' : ''} ${isActive ? 'bg-blue-50' : ''}`}>
                      <td className="px-3 py-2 text-center">
                        {isActive ? (
                          <span className="inline-block animate-spin text-blue-500" title="Processing">⏳</span>
                        ) : (
                          getStatusIcon(tenant)
                        )}
                      </td>
                      <td className="px-3 py-2 font-medium truncate max-w-[120px]" title={tenant.name}>
                        <div>{tenant.name}</div>
                        {isActive && liveProgress && (
                          <div className="text-xs text-blue-600 font-normal animate-pulse truncate" title={`${liveProgress.live_step}: ${liveProgress.live_details}`}>
                            {liveProgress.live_step}: {liveProgress.live_details}
                          </div>
                        )}
                      </td>
                      <td className="px-3 py-2 text-gray-600 text-xs truncate max-w-[100px]" title={tenant.domain || ''}>
                        {tenant.domain || '-'}
                      </td>
                      <td className="px-3 py-2 text-center">
                        {tenant.domain_added ? '✓' : '-'}
                      </td>
                      <td className="px-3 py-2 text-center">
                        {tenant.domain_verified ? '✓' : '-'}
                      </td>
                      <td className="px-3 py-2 text-center">
                        {tenant.dns_configured ? '✓' : '-'}
                      </td>
                      <td className="px-3 py-2 text-center">
                        {tenant.dkim_enabled ? '✓' : tenant.dkim_cnames_added ? '◐' : '-'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Status Legend */}
      <div className="flex flex-wrap gap-3 text-xs text-gray-600">
        <span>⚪ Not started</span>
        <span>🟡 In progress</span>
        <span>🟢 Complete</span>
        <span>🔴 Error</span>
        <span>✓ Done</span>
        <span>◐ Partial</span>
      </div>

      {/* Info Box */}
      <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 text-sm">
        <p className="text-yellow-800">
          <strong>⚠️ Prerequisites:</strong>
        </p>
        <ul className="mt-2 text-yellow-700 list-disc list-inside space-y-1">
          <li>Tenants must have completed first login (Step 4)</li>
          <li>Tenants must have OAuth tokens (from first login)</li>
          <li>Each tenant needs ~5 minutes (DNS propagation waits)</li>
        </ul>
      </div>

      {/* Continue Button */}
      <div className="border-t pt-6">
        {allComplete ? (
          <button
            onClick={async () => {
              await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/advance`, {
                method: 'POST'
              });
              onComplete();
              onNext();
            }}
            className="w-full py-4 bg-green-600 text-white text-lg font-bold rounded-lg hover:bg-green-700"
          >
            ✅ All Tenants Ready - Continue to Mailboxes →
          </button>
        ) : (
          <div className="space-y-3">
            <p className="text-sm text-gray-600 text-center">
              Complete M365 and DKIM setup for all tenants before continuing.
            </p>
            <button
              onClick={onNext}
              className="w-full py-3 border-2 border-gray-300 text-gray-600 font-medium rounded-lg hover:bg-gray-50"
            >
              Skip to Mailboxes (Not Recommended) →
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

interface TenantStep6Status {
  tenant_id: string;
  name: string;
  domain: string;
  onmicrosoft_domain: string;
  step5_complete: boolean;
  step6_started: boolean;
  step6_complete: boolean;
  step6_error: string | null;
  licensed_user: string | null;
  mailbox_count: number;
  progress: {
    mailboxes_created: number;
    display_names_fixed: number;
    accounts_enabled: number;
    passwords_set: number;
    upns_fixed: number;
    delegations_done: number;
  };
  live_progress: {
    step: string;
    status: string;
    detail: string;
    active: boolean;
  };
}

interface Step6DetailedStatus {
  batch_id: string;
  display_name: string | null;
  summary: {
    total_tenants: number;
    step5_complete: number;
    step6_complete: number;
    step6_errors: number;
    ready_for_step6: number;
  };
  tenants: TenantStep6Status[];
}

function Step6Mailboxes({ batchId, status, onComplete, onNext }: { batchId: string; status: WizardStatus | null; onComplete: () => void; onNext: () => void }) {
  const sequencerName = status?.sequencer_app_name || "Sequencer";
  const [step6Status, setStep6Status] = useState<Step6DetailedStatus | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isStarting, setIsStarting] = useState(false);
  const [isAutomationRunning, setIsAutomationRunning] = useState(false);
  const [isMarkingComplete, setIsMarkingComplete] = useState(false);
  const [isRerunning, setIsRerunning] = useState(false);
  const [isRetryingFailed, setIsRetryingFailed] = useState(false);
  const [isResettingStuck, setIsResettingStuck] = useState(false);
  const [isResumingProcessing, setIsResumingProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const summary = step6Status?.summary ?? {
    total_tenants: 0,
    step5_complete: 0,
    step6_complete: 0,
    step6_errors: 0,
    ready_for_step6: 0,
  };
  const totalTenants = summary.total_tenants;
  const completedTenants = summary.step6_complete;
  const readyForStep6 = summary.ready_for_step6;
  const step6Errors = summary.step6_errors;

  // Fetch step6 status
  const fetchStep6Status = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/step6/status`);
      if (!response.ok) throw new Error("Failed to fetch status");
      const data = await response.json();
      setStep6Status(data);
      
      // Set display name from batch if available
      if (data.display_name && !displayName) {
        setDisplayName(data.display_name);
      }
      
      // Check if automation is running
      const hasActiveProgress = data.tenants?.some((t: TenantStep6Status) => t.live_progress.active) ?? false;
      setIsAutomationRunning(hasActiveProgress);
      
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch status");
    } finally {
      setIsLoading(false);
    }
  }, [batchId, displayName]);

  // Initial fetch and polling
  useEffect(() => {
    fetchStep6Status();
    
    // Poll more frequently when automation is running
    const interval = setInterval(fetchStep6Status, isAutomationRunning ? 3000 : 10000);
    return () => clearInterval(interval);
  }, [fetchStep6Status, isAutomationRunning]);

  // Start automation
  const handleStartAutomation = async () => {
    if (!displayName.trim() || !displayName.includes(" ")) {
      setError("Please enter a full name (first and last name)");
      return;
    }

    setIsStarting(true);
    setError(null);

    try {
      const response = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/step6/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name: displayName.trim() }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || "Failed to start automation");
      }

      setIsAutomationRunning(true);
      fetchStep6Status();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start automation");
    } finally {
      setIsStarting(false);
    }
  };

  const handleForceComplete = async (tenantId: string) => {
    if (!confirm("Force-complete Step 6 for this tenant?")) return;

    try {
      const response = await fetch(`${API_BASE}/api/v1/wizard/tenants/${tenantId}/step6/force-complete`, {
        method: "POST",
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || "Failed to force complete Step 6");
      }

      await fetchStep6Status();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to force complete Step 6");
    }
  };

  // Mark batch as complete manually and advance to Step 7
  const handleMarkBatchComplete = async () => {
    if (!confirm(`Continue to Sequencer Setup (Step 7)? This will disable Security Defaults, enable SMTP Auth, and grant ${sequencerName} consent for all tenants.`)) return;
    
    setIsMarkingComplete(true);
    setError(null);
    
    try {
      const response = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/step6/mark-complete`, {
        method: "POST",
      });
      
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || "Failed to advance to Step 7");
      }
      
      // Advance to Step 7 (Sequencer Prep)
      onNext();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to advance to Step 7");
    } finally {
      setIsMarkingComplete(false);
    }
  };

  // Download CSV
  const handleDownloadCSV = async () => {
    try {
      const response = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/step6/export-csv`);
      if (!response.ok) throw new Error("Failed to download CSV");
      
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `mailboxes for upload - ${status?.batch_name || 'batch'}.csv`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to download CSV");
    }
  };

  // Rerun automation for remaining tenants
  const handleRerunAutomation = async () => {
    if (!displayName.trim() || !displayName.includes(" ")) {
      setError("Please enter a full name (first and last name)");
      return;
    }

    setIsRerunning(true);
    setError(null);

    try {
      const response = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/step6/rerun`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name: displayName.trim() }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || data.message || "Failed to rerun automation");
      }

      if (data.success) {
        setIsAutomationRunning(true);
        alert(`Restarted automation for ${data.eligible_count} tenant(s)`);
        fetchStep6Status();
      } else {
        setError(data.message || "No eligible tenants found");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to rerun automation");
    } finally {
      setIsRerunning(false);
    }
  };

  // Retry only failed tenants
  const handleRetryFailed = async () => {
    if (!displayName.trim() || !displayName.includes(" ")) {
      setError("Please enter a full name (first and last name)");
      return;
    }

    setIsRetryingFailed(true);
    setError(null);

    try {
      const response = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/step6/retry-failed`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name: displayName.trim() }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || data.message || "Failed to retry failed tenants");
      }

      if (data.success) {
        setIsAutomationRunning(true);
        alert(`Retrying ${data.failed_count} failed tenant(s)`);
        fetchStep6Status();
      } else {
        setError(data.message || "No failed tenants found");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to retry failed tenants");
    } finally {
      setIsRetryingFailed(false);
    }
  };

  // Reset stuck tenants
  const handleResetStuck = async () => {
    setIsResettingStuck(true);
    setError(null);

    try {
      const response = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/step6/reset-stuck`, {
        method: "POST",
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || data.message || "Failed to reset stuck tenants");
      }

      if (data.reset_count > 0) {
        alert(`Reset ${data.reset_count} stuck tenant(s). You can now rerun automation.`);
        fetchStep6Status();
      } else {
        alert("No stuck tenants found.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reset stuck tenants");
    } finally {
      setIsResettingStuck(false);
    }
  };

  // Resume Processing - One-click solution: resets stuck state AND immediately restarts automation
  const handleResumeProcessing = async () => {
    if (!displayName.trim() || !displayName.includes(" ")) {
      setError("Please enter a full name (first and last name)");
      return;
    }

    setIsResumingProcessing(true);
    setError(null);

    try {
      const response = await fetch(`${API_BASE}/api/v1/wizard/batches/${batchId}/step6/resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name: displayName.trim() }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || data.message || "Failed to resume processing");
      }

      if (data.success) {
        setIsAutomationRunning(true);
        alert(`Resumed processing for ${data.eligible_count} tenant(s)${data.reset_count > 0 ? ` (reset ${data.reset_count} stuck)` : ''}`);
        fetchStep6Status();
      } else {
        setError(data.message || "No eligible tenants found");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to resume processing");
    } finally {
      setIsResumingProcessing(false);
    }
  };

  // Get status icon
  const getStatusIcon = (tenant: TenantStep6Status) => {
    if (tenant.step6_complete) return "✅";
    if (tenant.step6_error) return "❌";
    if (tenant.live_progress.active) return "🔄";
    if (tenant.step6_started) return "⏳";
    if (!tenant.step5_complete) return "⚪";
    return "🟡";
  };

  // Get progress percentage
  const getProgressPercent = (tenant: TenantStep6Status) => {
    const total = 50 * 6; // 50 mailboxes × 6 steps
    const done = 
      tenant.progress.mailboxes_created +
      tenant.progress.display_names_fixed +
      tenant.progress.accounts_enabled +
      tenant.progress.passwords_set +
      tenant.progress.upns_fixed +
      tenant.progress.delegations_done;
    return Math.round((done / total) * 100);
  };

  if (isLoading) {
    return (
      <div className="text-center py-8">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
        <p className="mt-4 text-gray-600">Loading Step 6...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-xl font-bold text-gray-900">Step 6: Create Mailboxes</h2>
        <p className="text-gray-600 mt-2">
          Create 50 shared mailboxes per tenant and delegate to licensed user.
        </p>
      </div>

      {/* Error Alert */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-red-800">{error}</p>
          <button
            onClick={() => setError(null)}
            className="mt-2 text-sm text-red-600 hover:text-red-800"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Summary Cards */}
      {step6Status && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div className="bg-white rounded-lg shadow p-4 text-center">
            <div className="text-3xl font-bold text-gray-900">{totalTenants}</div>
            <div className="text-sm text-gray-500">Total Tenants</div>
          </div>
          <div className="bg-white rounded-lg shadow p-4 text-center">
            <div className="text-3xl font-bold text-blue-600">{summary.step5_complete}</div>
            <div className="text-sm text-gray-500">Step 5 Complete</div>
          </div>
          <div className="bg-white rounded-lg shadow p-4 text-center">
            <div className="text-3xl font-bold text-yellow-600">{readyForStep6}</div>
            <div className="text-sm text-gray-500">Ready for Step 6</div>
          </div>
          <div className="bg-white rounded-lg shadow p-4 text-center">
            <div className="text-3xl font-bold text-green-600">{completedTenants}</div>
            <div className="text-sm text-gray-500">Step 6 Complete</div>
          </div>
          <div className="bg-white rounded-lg shadow p-4 text-center">
            <div className="text-3xl font-bold text-red-600">{step6Errors}</div>
            <div className="text-sm text-gray-500">Errors</div>
          </div>
        </div>
      )}

      {/* Configuration Panel */}
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Configuration</h3>
        
        <div className="grid md:grid-cols-2 gap-6">
          {/* Display Name Input */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Display Name (for all mailboxes)
            </label>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="e.g., Jack Zuvelek"
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              disabled={isAutomationRunning}
            />
            <p className="mt-1 text-sm text-gray-500">
              Enter first and last name. This will be used for all 50 mailboxes per tenant.
            </p>
          </div>

          {/* Actions */}
          <div className="flex items-end gap-4">
            <button
              onClick={handleStartAutomation}
              disabled={isStarting || isAutomationRunning || !displayName.includes(" ")}
              className={`px-6 py-2 rounded-lg font-medium transition-colors ${
                isStarting || isAutomationRunning || !displayName.includes(" ")
                  ? "bg-gray-300 text-gray-500 cursor-not-allowed"
                  : "bg-blue-600 text-white hover:bg-blue-700"
              }`}
            >
              {isStarting ? "Starting..." : isAutomationRunning ? "Automation Running..." : "🚀 Start Mailbox Creation"}
            </button>

            {step6Status && completedTenants > 0 && (
              <button
                onClick={handleDownloadCSV}
                className="px-6 py-2 bg-green-600 text-white rounded-lg font-medium hover:bg-green-700 transition-colors"
              >
                📥 Download CSV
              </button>
            )}
          </div>
        </div>

        {/* Progress indicator when running */}
        {isAutomationRunning && (
          <div className="mt-6 p-4 bg-blue-50 rounded-lg">
            <div className="flex items-center gap-3">
              <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600"></div>
              <span className="text-blue-800 font-medium">Automation in progress...</span>
            </div>
            <p className="mt-2 text-sm text-blue-600">
              Processing {readyForStep6} tenant(s). This may take ~10 minutes per tenant.
            </p>
          </div>
        )}

        {/* Recovery Actions - shown when not running and there are incomplete/failed tenants */}
        {!isAutomationRunning && step6Status && (completedTenants < totalTenants || step6Errors > 0) && (
          <div className="mt-6 p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
            <h4 className="font-medium text-yellow-800 mb-3">Recovery Actions</h4>
            <div className="flex flex-wrap gap-3">
              {/* RESUME PROCESSING - Primary one-click solution */}
              {completedTenants < totalTenants && (
                <button
                  onClick={handleResumeProcessing}
                  disabled={isResumingProcessing || !displayName.includes(" ")}
                  className={`px-5 py-2.5 rounded-lg font-medium text-sm transition-colors ${
                    isResumingProcessing || !displayName.includes(" ")
                      ? "bg-gray-300 text-gray-500 cursor-not-allowed"
                      : "bg-green-600 text-white hover:bg-green-700"
                  }`}
                >
                  {isResumingProcessing ? (
                    <span className="flex items-center gap-2">
                      <span className="animate-spin">⏳</span>
                      Resuming...
                    </span>
                  ) : (
                    `▶️ Resume Processing (${totalTenants - completedTenants} pending)`
                  )}
                </button>
              )}

              {/* Retry Failed - show when there are errors */}
              {step6Errors > 0 && (
                <button
                  onClick={handleRetryFailed}
                  disabled={isRetryingFailed || !displayName.includes(" ")}
                  className={`px-4 py-2 rounded-lg font-medium text-sm transition-colors ${
                    isRetryingFailed || !displayName.includes(" ")
                      ? "bg-gray-300 text-gray-500 cursor-not-allowed"
                      : "bg-orange-600 text-white hover:bg-orange-700"
                  }`}
                >
                  {isRetryingFailed ? "Retrying..." : `🔁 Retry Failed (${step6Errors})`}
                </button>
              )}

              {/* Reset Stuck - available as advanced option */}
              <button
                onClick={handleResetStuck}
                disabled={isResettingStuck}
                className={`px-4 py-2 rounded-lg font-medium text-sm transition-colors ${
                  isResettingStuck
                    ? "bg-gray-300 text-gray-500 cursor-not-allowed"
                    : "bg-gray-600 text-white hover:bg-gray-700"
                }`}
              >
                {isResettingStuck ? "Resetting..." : "🧹 Reset Stuck Tenants"}
              </button>

              {/* Rerun for Remaining - secondary option */}
              {completedTenants < totalTenants && (
                <button
                  onClick={handleRerunAutomation}
                  disabled={isRerunning || !displayName.includes(" ")}
                  className={`px-4 py-2 rounded-lg font-medium text-sm transition-colors ${
                    isRerunning || !displayName.includes(" ")
                      ? "bg-gray-300 text-gray-500 cursor-not-allowed"
                      : "bg-blue-600 text-white hover:bg-blue-700"
                  }`}
                >
                  {isRerunning ? "Rerunning..." : `🔄 Rerun Remaining`}
                </button>
              )}
            </div>
            <p className="mt-2 text-xs text-yellow-700">
              💡 <strong>Resume Processing</strong> is the recommended one-click solution - it resets any stuck state and immediately restarts automation.
            </p>
          </div>
        )}
      </div>

      {/* Tenant Status Table */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
          <h3 className="text-lg font-semibold text-gray-900">Tenant Status</h3>
          <button
            onClick={fetchStep6Status}
            className="text-sm text-blue-600 hover:text-blue-800"
          >
            🔄 Refresh
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Tenant</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Domain</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Licensed User</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Mailboxes</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Progress</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Live Status</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {step6Status?.tenants?.map((tenant) => (
                <tr
                  key={tenant.tenant_id}
                  className={`${
                    tenant.step6_error
                      ? "bg-red-50"
                      : tenant.live_progress.active
                      ? "bg-blue-50"
                      : tenant.step6_complete
                      ? "bg-green-50"
                      : ""
                  }`}
                >
                  {/* Status Icon */}
                  <td className="px-4 py-3 text-center text-xl">
                    {getStatusIcon(tenant)}
                  </td>

                  {/* Tenant Name */}
                  <td className="px-4 py-3">
                    <div className="font-medium text-gray-900 truncate max-w-[150px]" title={tenant.name}>
                      {tenant.name}
                    </div>
                  </td>

                  {/* Domain */}
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {tenant.domain}
                  </td>

                  {/* Licensed User */}
                  <td className="px-4 py-3 text-sm">
                    {tenant.licensed_user ? (
                      <span className="text-green-600">{tenant.licensed_user}</span>
                    ) : (
                      <span className="text-gray-400">-</span>
                    )}
                  </td>

                  {/* Mailbox Count */}
                  <td className="px-4 py-3 text-sm">
                    <span className={tenant.mailbox_count === 50 ? "text-green-600 font-medium" : "text-gray-600"}>
                      {tenant.mailbox_count}/50
                    </span>
                  </td>

                  {/* Progress Bar */}
                  <td className="px-4 py-3">
                    {tenant.step6_started && (
                      <div className="w-32">
                        <div className="flex justify-between text-xs text-gray-500 mb-1">
                          <span>{getProgressPercent(tenant)}%</span>
                        </div>
                        <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-blue-600 transition-all duration-500"
                            style={{ width: `${getProgressPercent(tenant)}%` }}
                          />
                        </div>
                      </div>
                    )}
                  </td>

                  {/* Live Status */}
                  <td className="px-4 py-3 text-sm max-w-[200px]">
                    {tenant.step6_error ? (
                      <span className="text-red-600 truncate block" title={tenant.step6_error}>
                        ❌ {tenant.step6_error}
                      </span>
                    ) : tenant.live_progress.active ? (
                      <div className="text-blue-600">
                        <span className="animate-pulse">●</span>{" "}
                        <span className="font-medium">{tenant.live_progress.step}</span>
                        <div className="text-xs text-blue-500 truncate" title={tenant.live_progress.detail}>
                          {tenant.live_progress.detail}
                        </div>
                      </div>
                    ) : tenant.step6_complete ? (
                      <span className="text-green-600">✓ Complete</span>
                    ) : !tenant.step5_complete ? (
                      <span className="text-gray-400">Waiting for Step 5</span>
                    ) : (
                      <span className="text-gray-400">Ready</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right text-sm">
                    {!tenant.step6_complete && tenant.mailbox_count > 0 && (
                      <button
                        onClick={() => handleForceComplete(tenant.tenant_id)}
                        className="px-2 py-1 text-xs bg-yellow-100 text-yellow-800 rounded hover:bg-yellow-200"
                      >
                        Force Complete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Navigation */}
      <div className="flex justify-between items-center border-t pt-6">
        <button
          onClick={() => onComplete()}
          className="px-4 py-2 text-gray-600 hover:text-gray-800"
        >
          ← Back to Step 5
        </button>

        <div className="flex gap-4 items-center">
          {step6Status && completedTenants > 0 && (
            <button
              onClick={handleDownloadCSV}
              className="px-6 py-3 bg-green-600 text-white rounded-lg font-medium hover:bg-green-700 transition-colors"
            >
              📥 Download CSV
            </button>
          )}
          
          {/* Continue to Step 7 button */}
          {step6Status && completedTenants > 0 && (
            <button
              onClick={handleMarkBatchComplete}
              disabled={isMarkingComplete}
              className={`px-6 py-3 rounded-lg font-medium transition-colors ${
                isMarkingComplete
                  ? "bg-gray-300 text-gray-500 cursor-not-allowed"
                  : "bg-purple-600 text-white hover:bg-purple-700"
              }`}
            >
              {isMarkingComplete ? "Loading..." : "Continue to Sequencer Setup →"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

interface StepCompleteProps {
  batchId: string;
  status: WizardStatus | null;
  onGoBack?: (step: number) => void;
}

function StepComplete({ batchId, status, onGoBack }: StepCompleteProps) {
  return (
    <div className="text-center py-12">
      <div className="text-6xl mb-6">🎉</div>
      <h2 className="text-2xl font-bold">Setup Complete!</h2>
      <p className="text-gray-600 mt-4">{status?.mailboxes_ready || 0} mailboxes ready</p>
      <a href={`${API_BASE}/api/v1/wizard/batches/${batchId}/step6/export-credentials`}
        className="inline-block mt-6 px-6 py-3 bg-blue-600 text-white font-bold rounded-lg hover:bg-blue-700">
        📥 Download Credentials
      </a>
      
      {/* Navigation buttons */}
      <div className="mt-8 pt-6 border-t border-gray-200">
        <p className="text-sm text-gray-500 mb-4">Need to review or make changes?</p>
        <div className="flex justify-center gap-4 flex-wrap">
          <button
            onClick={() => onGoBack?.(7)}
            className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300 transition-colors"
          >
            ← Back to Sequencer (Step 7)
          </button>
          <button
            onClick={() => onGoBack?.(6)}
            className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300 transition-colors"
          >
            ← Back to Mailboxes (Step 6)
          </button>
          <button
            onClick={() => onGoBack?.(5)}
            className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300 transition-colors"
          >
            ← Back to Email Setup (Step 5)
          </button>
        </div>
      </div>
    </div>
  );
}
