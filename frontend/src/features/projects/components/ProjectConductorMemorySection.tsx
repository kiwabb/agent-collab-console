"use client";

import { useState } from "react";
import type { LucideIcon } from "lucide-react";
import { ChevronDown } from "lucide-react";

import { ProjectConductorExpandableText } from "@/features/projects/components/ProjectConductorExpandableText";
import {
  PROJECT_CONDUCTOR_MEMORY_PAGE_SIZE,
  nextProjectConductorVisibleCount,
} from "@/features/projects/projectConductorPresentation";
import { useI18n } from "@/providers/I18nProvider";

export interface ProjectConductorMemoryItem {
  id: string;
  body: string;
  meta?: string | undefined;
}

export function ProjectConductorMemorySection({
  title,
  description,
  empty,
  icon: Icon,
  items,
  truncated = false,
}: {
  title: string;
  description: string;
  empty: string;
  icon: LucideIcon;
  items: ProjectConductorMemoryItem[];
  truncated?: boolean;
}) {
  const { t } = useI18n();
  const [visibleCount, setVisibleCount] = useState(PROJECT_CONDUCTOR_MEMORY_PAGE_SIZE);
  const visibleItems = items.slice(0, visibleCount);
  const hasMore = visibleItems.length < items.length;
  const nextCount = Math.min(
    PROJECT_CONDUCTOR_MEMORY_PAGE_SIZE,
    items.length - visibleItems.length,
  );

  return (
    <section className="min-w-0 border-y border-border-subtle bg-surface px-4 py-4">
      <div className="flex items-start gap-3">
        <span className="flex size-8 shrink-0 items-center justify-center border border-brand/20 bg-brand/10 text-brand">
          <Icon size={15} aria-hidden />
        </span>
        <div className="min-w-0">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <h3 className="text-sm font-bold text-foreground">{title}</h3>
            <span className="text-[11px] tabular-nums text-text-muted">{items.length}</span>
          </div>
          <p className="mt-1 text-xs leading-5 text-text-muted">{description}</p>
        </div>
      </div>

      {items.length === 0 ? (
        <p className="mt-4 border-l-2 border-border-subtle pl-3 text-xs leading-5 text-text-muted">
          {empty}
        </p>
      ) : (
        <ul className="mt-4 divide-y divide-border-subtle border-y border-border-subtle">
          {visibleItems.map((item) => (
            <li key={item.id} className="py-3">
              {item.meta && (
                <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-text-muted">
                  {item.meta}
                </div>
              )}
              <ProjectConductorExpandableText text={item.body} />
            </li>
          ))}
        </ul>
      )}

      {hasMore && (
        <button
          type="button"
          onClick={() =>
            setVisibleCount((current) => nextProjectConductorVisibleCount(current, items.length))
          }
          className="mt-3 inline-flex min-h-9 items-center gap-1.5 text-xs font-semibold text-brand transition-colors hover:text-brand-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60"
        >
          <ChevronDown size={13} aria-hidden />
          {t("projectConductor.content.showNext", { count: nextCount })}
        </button>
      )}
      {truncated && !hasMore && (
        <p className="mt-3 text-[11px] leading-5 text-text-muted">
          {t("projectConductor.content.recentOnly")}
        </p>
      )}
    </section>
  );
}
