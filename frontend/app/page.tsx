"use client";

import { useState, useEffect } from "react";
import Link from "next/link";

interface BatchSummary {
  id: string;
  name: string;
  current_step: number;
  status: string;
  domains_count: number;
  tenants_count: number;
  mailboxes_count: number;
}

interface DashboardStats {
  total_batches: number;
  active_batches: number;
  completed_batches: number;
  total_domains: number;
  total_tenants: number;
  total_mailboxes: number;
  recent_batches: BatchSummary[];
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function Dashboard() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadStats();
  }, []);

  const loadStats = async () => {
    try {
      const batchRes = await fetch(`${API_BASE}/api/v1/wizard/batches`);
      const batches: BatchSummary[] = await batchRes.json();

      const calculatedStats: DashboardStats = {
        total_batches: batches.length,
        active_batches: batches.filter((b) => b.status === "active").length,
        completed_batches: batches.filter((b) => b.status === "completed").length,
        total_domains: batches.reduce((sum, b) => sum + b.domains_count, 0),
        total_tenants: batches.reduce((sum, b) => sum + b.tenants_count, 0),
        total_mailboxes: batches.reduce((sum, b) => sum + b.mailboxes_count, 0),
        recent_batches: batches.slice(0, 5),
      };

      setStats(calculatedStats);
    } catch (e) {
      console.error("Failed to load stats", e);
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

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="bg-white shadow">
        <div className="max-w-6xl mx-auto px-4 py-6">
          <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
          <p className="text-gray-600 mt-1">Cold Email Infrastructure Overview</p>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-4 py-8">
        <div className="bg-gradient-to-r from-blue-600 to-blue-700 rounded-lg p-6 mb-8 text-white">
          <h2 className="text-xl font-bold mb-2">Ready to set up more infrastructure?</h2>
          <p className="opacity-90 mb-4">
            Create a new batch to start setting up domains, tenants, and mailboxes.
          </p>
          <a
            href="/pipeline/new"
            className="inline-flex items-center gap-2 rounded-lg bg-white px-6 py-3 text-blue-600 font-semibold hover:bg-blue-50 transition-colors"
          >
            🚀 Start New Batch
          </a>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-8">
          <StatCard label="Total Batches" value={stats?.total_batches || 0} color="gray" />
          <StatCard label="Active" value={stats?.active_batches || 0} color="green" />
          <StatCard label="Completed" value={stats?.completed_batches || 0} color="blue" />
          <StatCard label="Domains" value={stats?.total_domains || 0} color="purple" />
          <StatCard label="Tenants" value={stats?.total_tenants || 0} color="orange" />
          <StatCard label="Mailboxes" value={stats?.total_mailboxes || 0} color="teal" />
        </div>

        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-bold text-gray-900">Recent Batches</h2>
            <Link href="/pipeline/new" className="text-blue-600 hover:underline text-sm">
              View All
            </Link>
          </div>

          {stats?.recent_batches && stats.recent_batches.length > 0 ? (
            <div className="space-y-3">
              {stats.recent_batches.map((batch) => (
                <Link
                  key={batch.id}
                  href={"/pipeline/" + batch.id}
                  className="block p-4 border rounded-lg hover:border-blue-300 hover:bg-blue-50 transition-colors"
                >
                  <div className="flex justify-between items-center">
                    <div>
                      <p className="font-medium text-gray-900">{batch.name}</p>
                      <p className="text-sm text-gray-500">
                        Step {batch.current_step} - {batch.domains_count} domains - {batch.mailboxes_count} mailboxes
                      </p>
                    </div>
                    <span
                      className={
                        "px-2 py-1 rounded-full text-xs font-medium " +
                        (batch.status === "completed"
                          ? "bg-blue-100 text-blue-800"
                          : batch.status === "active"
                          ? "bg-green-100 text-green-800"
                          : "bg-yellow-100 text-yellow-800")
                      }
                    >
                      {batch.status}
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-gray-500">
              <p>No batches yet. Create your first batch to get started!</p>
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-8">
          <Link
            href="/domains"
            className="p-4 bg-white rounded-lg shadow hover:shadow-md transition-shadow text-center"
          >
            <div className="text-3xl mb-2">
              <GlobeIcon />
            </div>
            <p className="font-medium">All Domains</p>
          </Link>
          <Link
            href="/tenants"
            className="p-4 bg-white rounded-lg shadow hover:shadow-md transition-shadow text-center"
          >
            <div className="text-3xl mb-2">
              <BuildingIcon />
            </div>
            <p className="font-medium">All Tenants</p>
          </Link>
        </div>
      </div>
    </div>
  );
}

function StatCard(props: { label: string; value: number; color: string }) {
  const colorClasses: Record<string, string> = {
    gray: "bg-gray-50 text-gray-600",
    green: "bg-green-50 text-green-600",
    blue: "bg-blue-50 text-blue-600",
    purple: "bg-purple-50 text-purple-600",
    orange: "bg-orange-50 text-orange-600",
    teal: "bg-teal-50 text-teal-600",
  };

  return (
    <div className={"rounded-lg p-4 " + (colorClasses[props.color] || colorClasses.gray)}>
      <p className="text-2xl font-bold">{props.value.toLocaleString()}</p>
      <p className="text-sm opacity-75">{props.label}</p>
    </div>
  );
}

function GlobeIcon() {
  return (
    <svg className="w-8 h-8 mx-auto text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 21a9 9 0 100-18 9 9 0 000 18z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 12h18M12 3a15 15 0 014 9 15 15 0 01-4 9 15 15 0 01-4-9 15 15 0 014-9z" />
    </svg>
  );
}

function BuildingIcon() {
  return (
    <svg className="w-8 h-8 mx-auto text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
    </svg>
  );
}

function MailIcon() {
  return (
    <svg className="w-8 h-8 mx-auto text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
    </svg>
  );
}