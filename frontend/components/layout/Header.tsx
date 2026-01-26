"use client";

interface HeaderProps {
  onMenuClick: () => void;
  title?: string;
}

export function Header({ onMenuClick, title = "Dashboard" }: HeaderProps) {
  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-4 border-b border-gray-200 bg-white px-4 sm:px-6">
      {/* Mobile menu button */}
      <button
        onClick={onMenuClick}
        className="rounded-md p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-500 lg:hidden"
      >
        <span className="sr-only">Open sidebar</span>
        <span className="text-xl">☰</span>
      </button>

      {/* Page title */}
      <div className="flex flex-1 items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-900">{title}</h1>

        {/* Right side actions */}
        <div className="flex items-center gap-4">
          {/* Refresh button */}
          <button
            className="rounded-md p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-500"
            title="Refresh"
          >
            <span className="text-lg">🔄</span>
          </button>

          {/* Status indicator */}
          <div className="hidden sm:flex items-center gap-2 text-sm text-gray-500">
            <span className="h-2 w-2 rounded-full bg-green-400"></span>
            <span>API Connected</span>
          </div>
        </div>
      </div>
    </header>
  );
}