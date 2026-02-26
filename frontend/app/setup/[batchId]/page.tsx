"use client";
import { useEffect } from "react";
import { useRouter, useParams } from "next/navigation";

export default function SetupBatchRedirect() {
  const router = useRouter();
  const params = useParams();
  useEffect(() => {
    router.replace(`/pipeline/${params.batchId}`);
  }, [router, params.batchId]);
  return (
    <div className="flex items-center justify-center min-h-screen">
      <p className="text-gray-500">Redirecting...</p>
    </div>
  );
}
