type BadgeVariant = "default" | "success" | "warning" | "error" | "info";

interface BadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
  className?: string;
}

const variantStyles: Record<BadgeVariant, string> = {
  default: "bg-gray-100 text-gray-800",
  success: "bg-green-100 text-green-800",
  warning: "bg-yellow-100 text-yellow-800",
  error: "bg-red-100 text-red-800",
  info: "bg-blue-100 text-blue-800",
};

export function Badge({ children, variant = "default", className = "" }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${variantStyles[variant]} ${className}`}
    >
      {children}
    </span>
  );
}

// Helper function to map domain status to badge variant
export function getStatusVariant(status: string): BadgeVariant {
  switch (status.toLowerCase()) {
    case "active":
    case "ready":
    case "complete":
    case "cf_zone_active":
      return "success";
    case "purchased":
    case "new":
    case "created":
    case "configuring":
      return "info";
    case "cf_zone_pending":
    case "ns_updating":
    case "ns_propagating":
    case "dns_configuring":
    case "pending_m365":
    case "pending_dkim":
    case "warming":
    case "early":
    case "ramping":
    case "mature":
      return "warning";
    case "problem":
    case "retired":
    case "suspended":
      return "error";
    default:
      return "default";
  }
}