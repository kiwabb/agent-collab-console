"use client";

import type { Artifact } from "@/lib/types";
import { FileText, ListTodo, Bug, FileJson, ChevronDown, ChevronRight, Package, Search } from "lucide-react";
import { useState, useMemo } from "react";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

interface ArtifactPanelProps {
  artifacts: Artifact[];
}

export function ArtifactPanel({ artifacts }: ArtifactPanelProps) {
  const { t } = useI18n();
  if (!artifacts || artifacts.length === 0) {
    return (
      <div className="flex flex-col h-full items-center justify-center text-text-muted">
        <Package size={48} strokeWidth={1} className="mb-4 opacity-10" />
        <p className="text-sm font-medium">{t("artifacts.empty")}</p>
      </div>
    );
  }

  const productArtifacts = useMemo(() => artifacts.filter((a) => a.kind === "product"), [artifacts]);
  const architectureArtifacts = useMemo(() => artifacts.filter((a) => a.kind === "architecture"), [artifacts]);
  const developmentArtifacts = useMemo(() => artifacts.filter((a) => a.kind === "development"), [artifacts]);
  const testingArtifacts = useMemo(() => artifacts.filter((a) => a.kind === "testing"), [artifacts]);
  const planArtifacts = useMemo(() => artifacts.filter((a) => a.kind === "plan"), [artifacts]);
  const execArtifacts = useMemo(() => artifacts.filter((a) => a.kind === "execution_result"), [artifacts]);
  const otherArtifacts = useMemo(() => artifacts.filter(
    (a) => !["product", "architecture", "development", "testing", "plan", "execution_result"].includes(a.kind)
  ), [artifacts]);

  return (
    <div className="flex flex-col h-full bg-background overflow-hidden">
      <div className="p-5 border-b border-border-subtle bg-surface/50">
        <h2 className="text-[10px] font-black uppercase tracking-[0.25em] text-text-muted">{t("artifacts.title")}</h2>
      </div>

      <div className="flex-1 overflow-y-auto p-5 space-y-10 no-scrollbar pb-20">
        {productArtifacts.length > 0 && (
          <ArtifactSection
            title={t("artifacts.product")}
            icon={<FileJson size={12} className="text-warning" />}
            artifacts={productArtifacts}
          />
        )}
        {architectureArtifacts.length > 0 && (
          <ArtifactSection
            title={t("artifacts.architecture")}
            icon={<FileText size={12} className="text-brand" />}
            artifacts={architectureArtifacts}
          />
        )}
        {developmentArtifacts.length > 0 && (
          <ArtifactSection
            title={t("artifacts.development")}
            icon={<ListTodo size={12} className="text-success" />}
            artifacts={developmentArtifacts}
          />
        )}
        {testingArtifacts.length > 0 && (
          <ArtifactSection
            title={t("artifacts.testing")}
            icon={<Bug size={12} className="text-error" />}
            artifacts={testingArtifacts}
          />
        )}
        {planArtifacts.length > 0 && (
          <ArtifactSection
            title={t("artifacts.strategy")}
            icon={<ListTodo size={12} className="text-success" />}
            artifacts={planArtifacts}
          />
        )}
        {execArtifacts.length > 0 && (
          <ArtifactSection
            title={t("artifacts.runtime")}
            icon={<Package size={12} className="text-brand" />}
            artifacts={execArtifacts}
          />
        )}
        {otherArtifacts.length > 0 && (
          <ArtifactSection
            title={t("artifacts.general")}
            artifacts={otherArtifacts}
          />
        )}
      </div>
    </div>
  );
}

function ArtifactSection({
  title,
  icon,
  artifacts,
}: {
  title: string;
  icon?: React.ReactNode;
  artifacts: Artifact[];
}) {
  return (
    <div className="animate-in fade-in duration-500">
      <h4 className="flex items-center gap-2.5 text-[10px] font-black text-text-muted uppercase tracking-[0.2em] mb-5 px-1">
        {icon || <div className="size-1.5 rounded-full bg-border-strong" />}
        {title}
      </h4>
      <div className="space-y-3">
        {artifacts.map((a) => (
          <ArtifactItem key={a.id} artifact={a} />
        ))}
      </div>
    </div>
  );
}

function ArtifactItem({ artifact }: { artifact: Artifact }) {
  const [open, setOpen] = useState(false);
  const label = artifact.name || artifact.kind;

  return (
    <div className={cn(
      "rounded-2xl border transition-all duration-300 overflow-hidden",
      open 
        ? "border-brand/40 bg-surface-raised shadow-lg shadow-brand/5" 
        : "border-border-subtle bg-surface/20 hover:border-border-strong hover:bg-surface/40"
    )}>
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-5 py-4 text-[13px] font-bold text-text-secondary hover:text-foreground transition-all group"
      >
        <div className="flex items-center gap-3.5 truncate">
          <div className={cn(
            "size-2 rounded-full transition-all",
            open ? "bg-brand shadow-[0_0_8px_rgba(122,157,204,0.6)]" : "bg-surface-input border border-border-strong"
          )} />
          <span className="truncate tracking-tight">{label}</span>
        </div>
        {open ? <ChevronDown size={16} className="text-brand" /> : <ChevronRight size={16} className="opacity-20 group-hover:opacity-100 transition-opacity" />}
      </button>
      {open && (
        <div className="px-5 pb-5 pt-0 animate-in slide-in-from-top-2 duration-300">
          <div className="relative group">
            <pre className="relative text-[12px] leading-relaxed text-text-secondary/80 whitespace-pre-wrap font-mono bg-background/60 p-5 rounded-xl border border-border-subtle max-h-96 overflow-y-auto no-scrollbar selection:bg-brand/30">
              {typeof artifact.content === "string"
                ? artifact.content
                : JSON.stringify(artifact.content, null, 2)}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}
