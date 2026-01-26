export default function DomainsLoading() {
  return (
    <div className="space-y-6">
      {/* Header skeleton */}
      <div className="flex justify-between items-center">
        <div className="h-8 w-48 bg-gray-200 rounded animate-pulse" />
        <div className="h-10 w-32 bg-gray-200 rounded animate-pulse" />
      </div>

      {/* Table skeleton */}
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        {/* Table header */}
        <div className="bg-gray-50 px-6 py-3 border-b border-gray-200">
          <div className="flex gap-8">
            <div className="h-4 w-24 bg-gray-200 rounded animate-pulse" />
            <div className="h-4 w-16 bg-gray-200 rounded animate-pulse" />
            <div className="h-4 w-32 bg-gray-200 rounded animate-pulse" />
            <div className="h-4 w-24 bg-gray-200 rounded animate-pulse" />
            <div className="h-4 w-20 bg-gray-200 rounded animate-pulse" />
            <div className="h-4 w-16 bg-gray-200 rounded animate-pulse ml-auto" />
          </div>
        </div>

        {/* Table rows */}
        {[...Array(5)].map((_, i) => (
          <div
            key={i}
            className="px-6 py-4 border-b border-gray-100 last:border-b-0"
          >
            <div className="flex items-center gap-8">
              {/* Domain column */}
              <div className="flex items-center gap-3 w-48">
                <div className="h-8 w-8 bg-gray-200 rounded animate-pulse" />
                <div className="space-y-1">
                  <div className="h-4 w-32 bg-gray-200 rounded animate-pulse" />
                  <div className="h-3 w-20 bg-gray-100 rounded animate-pulse" />
                </div>
              </div>
              
              {/* Status */}
              <div className="h-6 w-20 bg-gray-200 rounded-full animate-pulse" />
              
              {/* Nameservers */}
              <div className="space-y-1 w-40">
                <div className="h-3 w-36 bg-gray-200 rounded animate-pulse" />
                <div className="h-3 w-32 bg-gray-200 rounded animate-pulse" />
              </div>
              
              {/* DNS Records */}
              <div className="flex gap-1 w-32">
                {[...Array(4)].map((_, j) => (
                  <div key={j} className="h-5 w-8 bg-gray-200 rounded animate-pulse" />
                ))}
              </div>
              
              {/* Created */}
              <div className="h-4 w-24 bg-gray-200 rounded animate-pulse" />
              
              {/* Actions */}
              <div className="h-6 w-20 bg-gray-200 rounded animate-pulse ml-auto" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}