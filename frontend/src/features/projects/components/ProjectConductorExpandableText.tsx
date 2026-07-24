"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";
import { shouldCollapseProjectConductorText } from "@/features/projects/projectConductorPresentation";

export function ProjectConductorExpandableText({
  text,
  className,
  mono = false,
}: {
  text: string;
  className?: string;
  mono?: boolean;
}) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const collapsible = shouldCollapseProjectConductorText(text);

  return (
    <div className="min-w-0">
      <p
        className={cn(
          "whitespace-pre-wrap break-words text-xs leading-5 text-text-secondary",
          mono && "font-mono text-[11px]",
          collapsible && !expanded && "line-clamp-4",
          className,
        )}
      >
        {text}
      </p>
      {collapsible && (
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
          className="mt-2 inline-flex min-h-9 items-center gap-1.5 text-xs font-semibold text-brand transition-colors hover:text-brand-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60"
        >
          {expanded ? <ChevronUp size={13} aria-hidden /> : <ChevronDown size={13} aria-hidden />}
          {expanded
            ? t("projectConductor.content.showLess")
            : t("projectConductor.content.showMore")}
        </button>
      )}
    </div>
  );
}
