"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createTenant, TenantCreate } from "@/lib/api";

interface FormData {
  microsoft_tenant_id: string;
  name: string;
  onmicrosoft_domain: string;
  admin_email: string;
  admin_password: string;
}

interface FormErrors {
  microsoft_tenant_id?: string;
  name?: string;
  onmicrosoft_domain?: string;
  admin_email?: string;
  admin_password?: string;
}

const GUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function NewTenantPage() {
  const router = useRouter();
  const [formData, setFormData] = useState<FormData>({
    microsoft_tenant_id: "",
    name: "",
    onmicrosoft_domain: "",
    admin_email: "",
    admin_password: "",
  });
  const [errors, setErrors] = useState<FormErrors>({});
  const [loading, setLoading] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);

  const validateForm = (): boolean => {
    const newErrors: FormErrors = {};

    if (!formData.microsoft_tenant_id.trim()) {
      newErrors.microsoft_tenant_id = "Tenant ID is required";
    } else if (!GUID_REGEX.test(formData.microsoft_tenant_id.trim())) {
      newErrors.microsoft_tenant_id = "Invalid GUID format (e.g., xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)";
    }

    if (!formData.name.trim()) {
      newErrors.name = "Tenant name is required";
    } else if (formData.name.trim().length < 2) {
      newErrors.name = "Name must be at least 2 characters";
    }

    if (!formData.onmicrosoft_domain.trim()) {
      newErrors.onmicrosoft_domain = "OnMicrosoft domain is required";
    } else if (!formData.onmicrosoft_domain.trim().endsWith(".onmicrosoft.com")) {
      newErrors.onmicrosoft_domain = "Must end with .onmicrosoft.com";
    }

    if (!formData.admin_email.trim()) {
      newErrors.admin_email = "Admin email is required";
    } else if (!EMAIL_REGEX.test(formData.admin_email.trim())) {
      newErrors.admin_email = "Invalid email format";
    }

    if (!formData.admin_password) {
      newErrors.admin_password = "Password is required";
    } else if (formData.admin_password.length < 8) {
      newErrors.admin_password = "Password must be at least 8 characters";
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!validateForm()) {
      return;
    }

    setLoading(true);
    setSubmitError(null);

    try {
      const data: TenantCreate = {
        microsoft_tenant_id: formData.microsoft_tenant_id.trim(),
        name: formData.name.trim(),
        onmicrosoft_domain: formData.onmicrosoft_domain.trim().toLowerCase(),
        admin_email: formData.admin_email.trim().toLowerCase(),
        admin_password: formData.admin_password,
      };

      const tenant = await createTenant(data);
      router.push(`/tenants/${tenant.id}`);
    } catch (err) {
      console.error("Failed to create tenant:", err);
      setSubmitError("Failed to create tenant. Please check your inputs and try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleChange = (field: keyof FormData, value: string) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
    if (errors[field as keyof FormErrors]) {
      setErrors((prev) => ({ ...prev, [field]: undefined }));
    }
  };

  const inputClass = (hasError: boolean) =>
    `w-full px-4 py-3 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors ${
      hasError ? "border-red-300 bg-red-50" : "border-gray-300 bg-white"
    }`;

  return (
    <div className="max-w-2xl mx-auto">
      {/* Breadcrumb */}
      <div className="mb-6">
        <Link href="/tenants" className="text-blue-600 hover:text-blue-800 text-sm">
          Back to Tenants
        </Link>
      </div>

      {/* Form Card */}
      <div className="bg-white rounded-lg border border-gray-200 p-8">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Import M365 Tenant</h1>
          <p className="text-gray-500 mt-1">
            Add an existing Microsoft 365 tenant to manage mailboxes.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Microsoft Tenant ID */}
          <div>
            <label htmlFor="tenant_id" className="block text-sm font-medium text-gray-700 mb-2">
              Microsoft Tenant ID
            </label>
            <input
              type="text"
              id="tenant_id"
              value={formData.microsoft_tenant_id}
              onChange={(e) => handleChange("microsoft_tenant_id", e.target.value)}
              placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
              className={inputClass(!!errors.microsoft_tenant_id)}
            />
            {errors.microsoft_tenant_id && (
              <p className="mt-1 text-sm text-red-600">{errors.microsoft_tenant_id}</p>
            )}
            <p className="mt-1 text-xs text-gray-500">
              Find this in Azure Portal &rarr; Azure Active Directory &rarr; Overview
            </p>
          </div>

          {/* Tenant Name */}
          <div>
            <label htmlFor="name" className="block text-sm font-medium text-gray-700 mb-2">
              Tenant Name
            </label>
            <input
              type="text"
              id="name"
              value={formData.name}
              onChange={(e) => handleChange("name", e.target.value)}
              placeholder="e.g., North Region Tenant"
              className={inputClass(!!errors.name)}
            />
            {errors.name && <p className="mt-1 text-sm text-red-600">{errors.name}</p>}
          </div>

          {/* OnMicrosoft Domain */}
          <div>
            <label htmlFor="onmicrosoft" className="block text-sm font-medium text-gray-700 mb-2">
              OnMicrosoft Domain
            </label>
            <input
              type="text"
              id="onmicrosoft"
              value={formData.onmicrosoft_domain}
              onChange={(e) => handleChange("onmicrosoft_domain", e.target.value)}
              placeholder="yourcompany.onmicrosoft.com"
              className={inputClass(!!errors.onmicrosoft_domain)}
            />
            {errors.onmicrosoft_domain && (
              <p className="mt-1 text-sm text-red-600">{errors.onmicrosoft_domain}</p>
            )}
          </div>

          {/* Admin Email */}
          <div>
            <label htmlFor="admin_email" className="block text-sm font-medium text-gray-700 mb-2">
              Admin Email
            </label>
            <input
              type="email"
              id="admin_email"
              value={formData.admin_email}
              onChange={(e) => handleChange("admin_email", e.target.value)}
              placeholder="admin@yourcompany.onmicrosoft.com"
              className={inputClass(!!errors.admin_email)}
            />
            {errors.admin_email && (
              <p className="mt-1 text-sm text-red-600">{errors.admin_email}</p>
            )}
          </div>

          {/* Admin Password */}
          <div>
            <label htmlFor="admin_password" className="block text-sm font-medium text-gray-700 mb-2">
              Admin Password
            </label>
            <div className="relative">
              <input
                type={showPassword ? "text" : "password"}
                id="admin_password"
                value={formData.admin_password}
                onChange={(e) => handleChange("admin_password", e.target.value)}
                placeholder="Enter admin password"
                className={inputClass(!!errors.admin_password)}
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              >
                {showPassword ? "Hide" : "Show"}
              </button>
            </div>
            {errors.admin_password && (
              <p className="mt-1 text-sm text-red-600">{errors.admin_password}</p>
            )}
            <p className="mt-1 text-xs text-gray-500">
              This password is encrypted and used for mailbox provisioning.
            </p>
          </div>

          {/* Submit Error */}
          {submitError && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-4">
              <p className="text-sm text-red-700">{submitError}</p>
            </div>
          )}

          {/* Submit Buttons */}
          <div className="flex gap-4 pt-4">
            <button
              type="submit"
              disabled={loading}
              className="flex-1 px-4 py-3 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 transition-colors disabled:bg-blue-400 disabled:cursor-not-allowed flex items-center justify-center"
            >
              {loading ? (
                <>
                  <span className="animate-spin mr-2">*</span>
                  Creating Tenant...
                </>
              ) : (
                <>
                  <span className="mr-2">+</span>
                  Import Tenant
                </>
              )}
            </button>
            <Link
              href="/tenants"
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