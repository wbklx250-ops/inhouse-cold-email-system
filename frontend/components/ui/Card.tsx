interface CardProps {
  title: string;
  value: string | number;
  icon?: string;
  description?: string;
  className?: string;
}

export function Card({ title, value, icon, description, className = "" }: CardProps) {
  return (
    <div
      className={`bg-white rounded-lg border border-gray-200 p-6 shadow-sm hover:shadow-md transition-shadow ${className}`}
    >
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <p className="text-sm font-medium text-gray-500">{title}</p>
          <p className="mt-2 text-3xl font-semibold text-gray-900">{value}</p>
          {description && (
            <p className="mt-1 text-sm text-gray-500">{description}</p>
          )}
        </div>
        {icon && (
          <span className="text-3xl" role="img" aria-label={title}>
            {icon}
          </span>
        )}
      </div>
    </div>
  );
}

interface CardContainerProps {
  children: React.ReactNode;
  title?: string;
  className?: string;
}

export function CardContainer({ children, title, className = "" }: CardContainerProps) {
  return (
    <div className={`bg-white rounded-lg border border-gray-200 shadow-sm ${className}`}>
      {title && (
        <div className="border-b border-gray-200 px-6 py-4">
          <h3 className="text-lg font-medium text-gray-900">{title}</h3>
        </div>
      )}
      <div className="p-6">{children}</div>
    </div>
  );
}