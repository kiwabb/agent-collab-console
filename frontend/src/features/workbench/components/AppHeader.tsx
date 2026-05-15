"use client";

import { ChevronRight } from "lucide-react";
import { BackendStatusBadge } from "@/components/ui/backend-status-badge";

export interface BreadcrumbItem {
  label: string;
  href?: string;
}

interface Props {
  breadcrumbs?: BreadcrumbItem[];
  right?: React.ReactNode;
}

export function AppHeader({ breadcrumbs = [], right }: Props) {
  return (
    <header className="h-12 shrink-0 border-b border-border-subtle bg-surface flex items-center gap-3 px-4">
      <div className="flex items-center gap-1.5 min-w-0">
        {breadcrumbs.map((b, i) => (
          <span key={i} className="flex items-center gap-1.5 min-w-0">
            {b.href ? (
              <a
                href={b.href}
                className="text-sm text-text-muted hover:text-foreground transition-colors truncate"
              >
                {b.label}
              </a>
            ) : (
              <span className="text-sm font-semibold truncate">{b.label}</span>
            )}
            {i < breadcrumbs.length - 1 && (
              <ChevronRight size={12} className="text-text-muted shrink-0" />
            )}
          </span>
        ))}
      </div>
      <div className="ml-auto flex items-center gap-3">
        {right}
        <BackendStatusBadge />
      </div>
    </header>
  );
}
