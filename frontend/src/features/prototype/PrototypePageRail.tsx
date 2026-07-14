"use client";

import { Code2, FilePenLine, PanelsTopLeft, Plus, Route } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Loader } from "@/components/ui/loader";
import type { Prototype } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

import { readPrototypeRoutePatterns } from "./prototypeNavigation";

interface Props {
  prototypes: Prototype[] | null;
  activeId: string | null;
  onSelect: (prototype: Prototype) => void;
  onCreate: () => void;
}

export function PrototypePageRail({ prototypes, activeId, onSelect, onCreate }: Props) {
  const { t } = useI18n();

  return (
    <aside className="min-w-0 border-y border-border-subtle py-3 lg:border-y-0 lg:border-r lg:py-0 lg:pr-3">
      <div className="mb-2 flex min-h-11 items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <PanelsTopLeft className="shrink-0 text-text-muted" size={16} aria-hidden="true" />
          <h2 className="text-sm font-semibold">{t("prototype.pagesLabel")}</h2>
          {prototypes && <Badge variant="outline">{prototypes.length}</Badge>}
        </div>
        <Button
          className="min-h-11 min-w-11 lg:min-h-0 lg:min-w-0"
          size="icon-sm"
          variant="ghost"
          onClick={onCreate}
          aria-label={t("prototype.newTitle")}
          title={t("prototype.newTitle")}
        >
          <Plus size={15} />
        </Button>
      </div>

      {prototypes === null ? (
        <div className="flex h-24 items-center justify-center lg:h-40">
          <Loader variant="card" label={t("prototype.loading")} />
        </div>
      ) : prototypes.length === 0 ? (
        <EmptyState title={t("prototype.empty")} />
      ) : (
        <ul className="flex gap-2 overflow-x-auto overscroll-contain pb-1 lg:max-h-[calc(100dvh-18rem)] lg:flex-col lg:overflow-y-auto lg:pb-0">
          {prototypes.map((prototype) => {
            const route = readPrototypeRoutePatterns(prototype)[0] ?? null;
            const active = activeId === prototype.id;
            const SourceIcon = prototype.source_kind === "code" ? Code2 : FilePenLine;
            return (
              <li key={prototype.id} className="shrink-0 lg:w-full">
                <button
                  type="button"
                  onClick={() => onSelect(prototype)}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "group flex min-h-[5.25rem] w-[13.5rem] flex-col justify-between rounded-lg border px-3 py-2.5 text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring lg:w-full",
                    active
                      ? "border-brand bg-brand/10 text-foreground"
                      : "border-border-subtle bg-surface-base/50 text-text-muted hover:border-foreground/20 hover:bg-surface-raised hover:text-foreground",
                  )}
                >
                  <span className="flex w-full min-w-0 items-center justify-between gap-2">
                    <span className="truncate text-sm font-semibold">{prototype.title}</span>
                    <Badge
                      className="shrink-0 font-mono"
                      variant={active ? "secondary" : "outline"}
                    >
                      v{prototype.current_version}
                    </Badge>
                  </span>
                  <span className="flex w-full min-w-0 items-center justify-between gap-2 text-xs">
                    <span className="flex min-w-0 items-center gap-1.5 font-mono">
                      <Route size={12} aria-hidden="true" />
                      <span className="truncate">{route ?? t("prototype.routeMissing")}</span>
                    </span>
                    <span className="flex shrink-0 items-center gap-1">
                      <SourceIcon size={12} aria-hidden="true" />
                      {t(`prototype.source.${prototype.source_kind}`)}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </aside>
  );
}
