"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface EmptyStateProps {
  icon?: "workspace" | "issue" | "task" | "artifact" | "log" | "message" | "search" | "error";
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}

const illustrations = {
  workspace: (
    <svg width="64" height="64" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="8" y="12" width="48" height="40" rx="4" stroke="currentColor" strokeWidth="2" strokeDasharray="4 2" opacity="0.3"/>
      <rect x="14" y="18" width="20" height="12" rx="2" stroke="currentColor" strokeWidth="1.5" opacity="0.5"/>
      <rect x="38" y="18" width="12" height="8" rx="2" stroke="currentColor" strokeWidth="1.5" opacity="0.4"/>
      <rect x="14" y="34" width="16" height="10" rx="2" stroke="currentColor" strokeWidth="1.5" opacity="0.4"/>
      <circle cx="48" cy="44" r="6" stroke="currentColor" strokeWidth="1.5" opacity="0.3"/>
      <path d="M46 44h4M48 42v4" stroke="currentColor" strokeWidth="1.5" opacity="0.5"/>
    </svg>
  ),
  issue: (
    <svg width="64" height="64" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="10" y="8" width="44" height="48" rx="4" stroke="currentColor" strokeWidth="2" strokeDasharray="4 2" opacity="0.3"/>
      <path d="M20 20h24M20 28h16M20 36h20M20 44h12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" opacity="0.4"/>
      <circle cx="48" cy="16" r="8" fill="currentColor" opacity="0.1"/>
      <path d="M45 16l2 2 4-4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  task: (
    <svg width="64" height="64" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="12" y="14" width="40" height="36" rx="3" stroke="currentColor" strokeWidth="2" strokeDasharray="4 2" opacity="0.3"/>
      <path d="M24 26h16M24 34h12M24 42h8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" opacity="0.4"/>
      <circle cx="44" cy="44" r="10" stroke="currentColor" strokeWidth="2" opacity="0.3"/>
      <path d="M44 40v4l3 3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" opacity="0.5"/>
    </svg>
  ),
  artifact: (
    <svg width="64" height="64" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M12 12l8-8h24l8 8v40l-8 8H20l-8-8V12z" stroke="currentColor" strokeWidth="2" strokeDasharray="4 2" opacity="0.3"/>
      <path d="M20 24h24M20 32h16M20 40h20" stroke="currentColor" strokeWidth="2" strokeLinecap="round" opacity="0.4"/>
      <circle cx="48" cy="48" r="8" stroke="currentColor" strokeWidth="1.5" opacity="0.3"/>
    </svg>
  ),
  log: (
    <svg width="64" height="64" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="10" y="12" width="44" height="40" rx="3" stroke="currentColor" strokeWidth="2" strokeDasharray="4 2" opacity="0.3"/>
      <path d="M18 24l6 4-6 4M30 32h16" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" opacity="0.5"/>
      <path d="M18 36l4 2-4 2" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" opacity="0.3"/>
      <circle cx="50" cy="50" r="6" stroke="currentColor" strokeWidth="1.5" opacity="0.2"/>
    </svg>
  ),
  message: (
    <svg width="64" height="64" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M8 12c0-2.2 1.8-4 4-4h40c2.2 0 4 1.8 4 4v28c0 2.2-1.8 4-4 4H20l-8 8V12z" stroke="currentColor" strokeWidth="2" strokeDasharray="4 2" opacity="0.3"/>
      <path d="M20 24h24M20 32h16M20 40h20" stroke="currentColor" strokeWidth="2" strokeLinecap="round" opacity="0.4"/>
    </svg>
  ),
  search: (
    <svg width="64" height="64" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="28" cy="28" r="16" stroke="currentColor" strokeWidth="2" strokeDasharray="4 2" opacity="0.3"/>
      <path d="M40 40l12 12" stroke="currentColor" strokeWidth="3" strokeLinecap="round" opacity="0.5"/>
      <path d="M22 28h12M28 22v12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" opacity="0.4"/>
    </svg>
  ),
  error: (
    <svg width="64" height="64" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="32" cy="32" r="24" stroke="currentColor" strokeWidth="2" strokeDasharray="4 2" opacity="0.3"/>
      <path d="M24 24l16 16M40 24L24 40" stroke="currentColor" strokeWidth="3" strokeLinecap="round" opacity="0.5"/>
    </svg>
  ),
};

export function EmptyState({ icon = "workspace", title, description, action, className }: EmptyStateProps) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-4 p-8 text-center", className)}>
      <div className="text-text-muted/30">
        {illustrations[icon]}
      </div>
      <div className="space-y-1">
        <p className="text-sm font-bold text-text-muted">{title}</p>
        {description && (
          <p className="text-xs text-text-muted/60 max-w-xs">{description}</p>
        )}
      </div>
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}