"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function SetupRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/pipeline/new");
  }, [router]);
  return (
    <div className="flex items-center justify-center min-h-screen">
      <p className="text-gray-500">Redirecting to new batch setup...</p>
    </div>
  );
}
