"use client";

import { useRef, useState, useMemo } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { Artifact } from "@/lib/types";
import { FileText, ListTodo, Bug, FileJson, ChevronDown, ChevronRight, Package, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";
import { motion, AnimatePresence } from "framer-motion";

interface VirtualizedArtifactListProps {
  artifacts: Artifact[];
  isLoading?: boolean;
  maxHeight?: string;
}

export function VirtualizedArtifactList({ artifacts, isLoading, maxHeight = "100%" }: VirtualizedArtifactListProps) {
  const { t } = useI18n();
  const parentRef = useRef<HTMLDivElement>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const productArtifacts = useMemo(() => artifacts.filter((a) => a.kind === "product"), [artifacts]);
  const architectureArtifacts = useMemo(() => artifacts.filter((a) => a.kind === "architecture"), [artifacts]);
  const developmentArtifacts = useMemo(() => artifacts.filter((a) => a.kind === "development"), [artifacts]);
  const testingArtifacts = useMemo(() => artifacts.filter((a) => a.kind === "testing"), [artifacts]);
  const planArtifacts = useMemo(() => artifacts.filter((a) => a.kind === "plan"), [artifacts]);
  const execArtifacts = useMemo(() => artifacts.filter((a) => a.kind === "execution_result"), [artifacts]);
  const otherArtifacts = useMemo(() => artifacts.filter(
    (a) => !["product", "architecture", "development", "testing", "plan", "execution_result"].includes(a.kind)
  ), [artifacts]);

  const allSections = useMemo(() => [
    { id: "product", label: t("artifacts.product"), icon: <FileJson size={12} className="text-warning" />, items: productArtifacts },
    { id: "architecture", label: t("artifacts.architecture"), icon: <FileText size={12} className="text-brand" />, items: architectureArtifacts },
    { id: "development", label: t("artifacts.development"), icon: <ListTodo size={12} className="text-success" />, items: developmentArtifacts },
    { id: "testing", label: t("artifacts.testing"), icon: <Bug size={12} className="text-error" />, items: testingArtifacts },
    { id: "plan", label: t("artifacts.strategy"), icon: <ListTodo size={12} className="text-success" />, items: planArtifacts },
    { id: "execution_result", label: t("artifacts.runtime"), icon: <Package size={12} className="text-brand" />, items: execArtifacts },
    { id: "other", label: t("artifacts.general"), items: otherArtifacts },
  ].filter(section => section.items.length > 0), [t, productArtifacts, architectureArtifacts, developmentArtifacts, testingArtifacts, planArtifacts, execArtifacts, otherArtifacts]);

  const flatItems = useMemo(() => {
    const items: Array<{ type: "header" | "item"; data: any; index: number }> = [];
    allSections.forEach((section, sectionIdx) => {
      items.push({ type: "header", data: section, index: items.length });
      section.items.forEach((artifact) => {
        items.push({ type: "item", data: artifact, index: items.length });
      });
    });
    return items;
  }, [allSections]);

  const virtualizer = useVirtualizer({
    count: flatItems.length,
    getScrollElement: () => parentRef.current,
    estimateSize: (index) => flatItems[index].type === "header" ? 40 : expandedId === flatItems[index].data.id ? 300 : 60,
    overscan: 5,
  });

  if (isLoading) {
    return (
      <div className="flex flex-col h-full overflow-hidden">
        <div className="p-5 border-b border-border-subtle bg-surface/50">
          <div className="h-4 w-24 bg-surface-raised animate-pulse rounded" />
        </div>
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="h-16 bg-surface-raised animate-pulse rounded-2xl" />
          ))}
        </div>
      </div>
    );
  }

  if (!artifacts || artifacts.length === 0) {
    return (
      <div className="flex flex-col h-full items-center justify-center text-text-muted/30 py-16">
        <div className="size-14 rounded-2xl bg-surface-raised border border-border-subtle flex items-center justify-center mb-4">
          <Package size={24} strokeWidth={1} className="opacity-50" />
        </div>
        <p className="text-xs font-bold uppercase tracking-widest">{t("artifacts.empty")}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="p-5 border-b border-border-subtle bg-surface/50 shrink-0">
        <h2 className="text-[10px] font-black uppercase tracking-[0.25em] text-text-muted">
          {t("artifacts.title")} ({artifacts.length})
        </h2>
      </div>

      <div ref={parentRef} className="flex-1 overflow-y-auto" style={{ maxHeight }}>
        <div
          style={{ height: `${virtualizer.getTotalSize()}px`, width: "100%", position: "relative" }}
        >
          {virtualizer.getVirtualItems().map((virtualRow) => {
            const item = flatItems[virtualRow.index];

            if (item.type === "header") {
              const section = item.data;
              return (
                <div
                  key={section.id}
                  data-index={virtualRow.index}
                  ref={virtualizer.measureElement}
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: "100%",
                    transform: `translateY(${virtualRow.start}px)`,
                  }}
                >
                  <h4 className="flex items-center gap-2.5 text-[10px] font-black text-text-muted uppercase tracking-[0.2em] px-5 py-3">
                    {section.icon || <div className="size-1.5 rounded-full bg-border-strong" />}
                    {section.label}
                    <span className="text-[9px] bg-surface-raised px-1.5 py-0.5 rounded-full border border-border-subtle">
                      {section.items.length}
                    </span>
                  </h4>
                </div>
              );
            }

            const artifact = item.data;
            const isExpanded = expandedId === artifact.id;
            const label = artifact.name || artifact.kind;

            return (
              <div
                key={artifact.id}
                data-index={virtualRow.index}
                ref={virtualizer.measureElement}
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  width: "100%",
                  transform: `translateY(${virtualRow.start}px)`,
                }}
              >
                <ArtifactItem
                  artifact={artifact}
                  isExpanded={isExpanded}
                  onToggle={() => setExpandedId(isExpanded ? null : artifact.id)}
                />
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function ArtifactItem({
  artifact,
  isExpanded,
  onToggle,
}: {
  artifact: Artifact;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const label = artifact.name || artifact.kind;

  return (
    <motion.div
      layout
      className={cn(
        "mx-3 my-1.5 rounded-2xl border transition-all duration-300 overflow-hidden",
        isExpanded
          ? "border-brand/40 bg-surface-raised shadow-lg shadow-brand/5"
          : "border-border-subtle bg-surface/20 hover:border-border-strong hover:bg-surface/40"
      )}
    >
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-5 py-4 text-[13px] font-bold text-text-secondary hover:text-foreground transition-all group"
      >
        <div className="flex items-center gap-3.5 truncate">
          <div className={cn(
            "size-2 rounded-full transition-all",
            isExpanded ? "bg-brand shadow-[0_0_8px_rgba(122,157,204,0.6)]" : "bg-surface-input border border-border-strong"
          )} />
          <span className="truncate tracking-tight">{label}</span>
        </div>
        {isExpanded ? (
          <ChevronDown size={16} className="text-brand" />
        ) : (
          <ChevronRight size={16} className="opacity-20 group-hover:opacity-100 transition-opacity" />
        )}
      </button>
      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="px-5 pb-5 pt-0">
              <pre className="text-[12px] leading-relaxed text-text-secondary/80 whitespace-pre-wrap font-mono bg-background/60 p-5 rounded-xl border border-border-subtle max-h-80 overflow-y-auto no-scrollbar selection:bg-brand/30">
                {typeof artifact.content === "string"
                  ? artifact.content
                  : JSON.stringify(artifact.content, null, 2)}
              </pre>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
