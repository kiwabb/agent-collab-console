"use client";

import { useRef, useState, useMemo, useEffect, type ReactNode } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { Artifact } from "@/lib/types";
import { FileText, ListTodo, Bug, FileJson, ChevronDown, ChevronRight, Package, Copy, Check, Download, ZoomIn, ZoomOut, Maximize2, Minimize2, WrapText, Search, Hash, GitCompare, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";
import { motion, AnimatePresence } from "framer-motion";
import hljs from "highlight.js/lib/core";
import json from "highlight.js/lib/languages/json";
import javascript from "highlight.js/lib/languages/javascript";
import typescript from "highlight.js/lib/languages/typescript";
import bash from "highlight.js/lib/languages/bash";
import markdown from "highlight.js/lib/languages/markdown";
import xml from "highlight.js/lib/languages/xml";
import css from "highlight.js/lib/languages/css";

hljs.registerLanguage("json", json);
hljs.registerLanguage("javascript", javascript);
hljs.registerLanguage("typescript", typescript);
hljs.registerLanguage("bash", bash);
hljs.registerLanguage("markdown", markdown);
hljs.registerLanguage("xml", xml);
hljs.registerLanguage("css", css);

function formatRelativeTime(dateStr: string | null): string {
  if (!dateStr) return "";
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHour = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHour / 24);
  if (diffSec < 60) return `${diffSec}s ago`;
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHour < 24) return `${diffHour}h ago`;
  if (diffDay < 7) return `${diffDay}d ago`;
  return date.toLocaleDateString();
}

function detectLanguage(content: string, filename?: string): string {
  if (filename) {
    if (filename.endsWith(".json")) return "json";
    if (filename.endsWith(".ts") || filename.endsWith(".tsx")) return "typescript";
    if (filename.endsWith(".js") || filename.endsWith(".jsx")) return "javascript";
    if (filename.endsWith(".md")) return "markdown";
    if (filename.endsWith(".sh") || filename.endsWith(".bash")) return "bash";
    if (filename.endsWith(".css")) return "css";
    if (filename.endsWith(".html") || filename.endsWith(".xml")) return "xml";
  }
  try {
    JSON.parse(content);
    return "json";
  } catch {}
  if (content.includes("function") || content.includes("const ") || content.includes("let ")) {
    return "javascript";
  }
  if (content.includes("<") && content.includes("/>")) return "xml";
  return "markdown";
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

interface HighlightedCodeProps {
  code: string;
  language: string;
  zoom?: number;
  wordWrap?: boolean;
  showLineNumbers?: boolean;
  previousContent?: string;
}

export function HighlightedCode({ code, language, zoom = 100, wordWrap = true, showLineNumbers = false, previousContent }: HighlightedCodeProps) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  const [showSearch, setShowSearch] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [showDiff, setShowDiff] = useState(false);
  const [jumpToLine, setJumpToLine] = useState("");
  const [lineNumbersOn, setLineNumbersOn] = useState(showLineNumbers);

  const highlighted = useMemo(() => {
    try {
      if (hljs.getLanguage(language)) {
        return hljs.highlight(code, { language }).value;
      }
      return hljs.highlightAuto(code).value;
    } catch {
      return escapeHtml(code);
    }
  }, [code, language]);

  const lines = code.split("\n");

  const searchMatches = useMemo(() => {
    if (!searchQuery) return [];
    const matches: number[] = [];
    lines.forEach((line, idx) => {
      if (line.toLowerCase().includes(searchQuery.toLowerCase())) matches.push(idx);
    });
    return matches;
  }, [searchQuery, lines]);

  useEffect(() => {
    if (jumpToLine) {
      const lineNum = parseInt(jumpToLine);
      if (lineNum > 0 && lineNum <= lines.length) {
        const el = document.querySelector(`[data-line="${lineNum}"]`);
        if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }
  }, [jumpToLine, lines.length]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "f") {
        e.preventDefault();
        setShowSearch(true);
      }
      if (e.key === "Escape") {
        setShowSearch(false);
        setSearchQuery("");
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const handleCopy = () => {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  const handleDownload = () => {
    const blob = new Blob([code], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `artifact.${language === "json" ? "json" : "txt"}`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const renderDiff = () => {
    if (!previousContent || !showDiff) return null;
    const prevLines = previousContent.split("\n");
    return (
      <div className="flex gap-2 font-mono text-[12px] p-5">
        <div className="flex-1">
          <div className="text-text-muted/50 mb-2 uppercase tracking-wider text-[10px] font-black">{t("ui.previous")}</div>
          {prevLines.map((line, i) => (
            <div key={i} className={cn("py-0.5 pr-4", line && "bg-red-500/10 text-red-400/70")}>
              <span className="text-text-muted/30 mr-3 select-none">{i + 1}</span>
              {line || " "}
            </div>
          ))}
        </div>
        <div className="flex-1">
          <div className="text-text-muted/50 mb-2 uppercase tracking-wider text-[10px] font-black">{t("ui.current")}</div>
          {lines.map((line, i) => (
            <div key={i} className={cn("py-0.5 pr-4", line && "bg-green-500/10 text-green-400/70")}>
              <span className="text-text-muted/30 mr-3 select-none">{i + 1}</span>
              {line || " "}
            </div>
          ))}
        </div>
      </div>
    );
  };

  return (
    <div className="relative group/code">
      <div className="absolute top-3 right-3 flex items-center gap-1 z-10 opacity-0 group-hover/code:opacity-100 transition-opacity">
        <button onClick={() => setLineNumbersOn(l => !l)} className="p-1.5 rounded-lg bg-surface-raised border border-border-subtle hover:bg-surface-hover transition-all" aria-label={t("ui.toggleLineNumbers")}>
          <Hash size={14} className={cn("text-text-muted", lineNumbersOn && "text-brand")} />
        </button>
        <button onClick={() => setShowSearch(s => !s)} className="p-1.5 rounded-lg bg-surface-raised border border-border-subtle hover:bg-surface-hover transition-all" aria-label={t("ui.search")}>
          <Search size={14} className={cn("text-text-muted", showSearch && "text-brand")} />
        </button>
        {previousContent && (
          <button onClick={() => setShowDiff(d => !d)} className="p-1.5 rounded-lg bg-surface-raised border border-border-subtle hover:bg-surface-hover transition-all" aria-label={t("ui.toggleDiffView")}>
            <GitCompare size={14} className={cn("text-text-muted", showDiff && "text-brand")} />
          </button>
        )}
        <button onClick={handleCopy} className="p-1.5 rounded-lg bg-surface-raised border border-border-subtle hover:bg-surface-hover transition-all" aria-label={t("ui.copyCode")}>
          {copied ? <Check size={14} className="text-success" /> : <Copy size={14} className="text-text-muted" />}
        </button>
        <button onClick={handleDownload} className="p-1.5 rounded-lg bg-surface-raised border border-border-subtle hover:bg-surface-hover transition-all" aria-label={t("ui.downloadArtifact")}>
          <Download size={14} className="text-text-muted" />
        </button>
      </div>
      {showSearch && (
        <div className="absolute top-3 left-3 z-10 flex items-center gap-2 bg-surface-raised border border-border-subtle rounded-lg p-2">
          <Search size={12} className="text-text-muted" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t("ui.searchPlaceholder")}
            className="bg-transparent text-[12px] w-40 outline-none text-text-primary placeholder:text-text-muted/50"
            autoFocus
          />
          {searchQuery && <span className="text-[10px] text-text-muted">{t("ui.matchCount", { count: searchMatches.length })}</span>}
          <button onClick={() => { setShowSearch(false); setSearchQuery(""); }} className="p-0.5 hover:bg-surface-hover rounded"><X size={12} className="text-text-muted" /></button>
        </div>
      )}
      {lineNumbersOn && (
        <div className="absolute top-3 left-3 z-10 flex items-center gap-1 bg-surface-raised border border-border-subtle rounded-lg p-1.5">
          <span className="text-[10px] text-text-muted/50 mr-1">{t("ui.line")}</span>
          <input
            type="text"
            value={jumpToLine}
            onChange={(e) => setJumpToLine(e.target.value.replace(/\D/g, ""))}
            placeholder="#"
            className="bg-transparent text-[11px] w-10 outline-none text-text-primary font-mono"
          />
          {jumpToLine && (
            <button onClick={() => setJumpToLine("")} className="p-0.5 hover:bg-surface-hover rounded"><X size={10} className="text-text-muted" /></button>
          )}
        </div>
      )}
      {showDiff ? renderDiff() : (
        <code
          className={cn(
            "text-[12px] leading-relaxed [&_.hljs-keyword]:text-pink-400 [&_.hljs-string]:text-green-400 [&_.hljs-number]:text-orange-400 [&_.hljs-comment]:text-gray-500 [&_.hljs-attr]:text-cyan-400 [&_.hljs-title]:text-blue-400 [&_.hljs-built_in]:text-purple-400 [&_.hljs-literal]:text-orange-400 [&_.hljs-type]:text-cyan-300 [&_.hljs-params]:text-yellow-300 [&_.hljs-meta]:text-gray-400",
            "whitespace-pre-wrap font-mono bg-background/60 p-5 rounded-xl border border-border-subtle max-h-80 overflow-y-auto no-scrollbar selection:bg-brand/30 block",
            lineNumbersOn && "pl-12"
          )}
          style={{ fontSize: `${zoom}%`, whiteSpace: wordWrap ? "pre-wrap" : "pre" }}
          dangerouslySetInnerHTML={{ __html: highlighted }}
        />
      )}
    </div>
  );
}

interface VirtualizedArtifactListProps {
  artifacts: Artifact[];
  isLoading?: boolean;
  maxHeight?: string;
}

interface ArtifactSection {
  id: string;
  label: string;
  icon?: ReactNode;
  items: Artifact[];
}

type FlatArtifactItem =
  | { type: "header"; data: ArtifactSection; index: number }
  | { type: "item"; data: Artifact; index: number };

export function VirtualizedArtifactList({ artifacts, isLoading, maxHeight = "100%" }: VirtualizedArtifactListProps) {
  const { t } = useI18n();
  const parentRef = useRef<HTMLDivElement>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [zoom, setZoom] = useState(100);
  const [wordWrap, setWordWrap] = useState(true);
  const [isFullscreen, setIsFullscreen] = useState(false);

  const productArtifacts = useMemo(() => artifacts.filter((a) => a.kind === "product"), [artifacts]);
  const architectureArtifacts = useMemo(() => artifacts.filter((a) => a.kind === "architecture"), [artifacts]);
  const developmentArtifacts = useMemo(() => artifacts.filter((a) => a.kind === "development"), [artifacts]);
  const testingArtifacts = useMemo(() => artifacts.filter((a) => a.kind === "testing"), [artifacts]);
  const planArtifacts = useMemo(() => artifacts.filter((a) => a.kind === "plan"), [artifacts]);
  const execArtifacts = useMemo(() => artifacts.filter((a) => a.kind === "execution_result"), [artifacts]);
  const otherArtifacts = useMemo(() => artifacts.filter(
    (a) => !["product", "architecture", "development", "testing", "plan", "execution_result"].includes(a.kind)
  ), [artifacts]);

  const allSections = useMemo<ArtifactSection[]>(() => [
    { id: "product", label: t("artifacts.product"), icon: <FileJson size={12} className="text-warning" />, items: productArtifacts },
    { id: "architecture", label: t("artifacts.architecture"), icon: <FileText size={12} className="text-brand" />, items: architectureArtifacts },
    { id: "development", label: t("artifacts.development"), icon: <ListTodo size={12} className="text-success" />, items: developmentArtifacts },
    { id: "testing", label: t("artifacts.testing"), icon: <Bug size={12} className="text-error" />, items: testingArtifacts },
    { id: "plan", label: t("artifacts.strategy"), icon: <ListTodo size={12} className="text-success" />, items: planArtifacts },
    { id: "execution_result", label: t("artifacts.runtime"), icon: <Package size={12} className="text-brand" />, items: execArtifacts },
    { id: "other", label: t("artifacts.general"), items: otherArtifacts },
  ].filter(section => section.items.length > 0), [t, productArtifacts, architectureArtifacts, developmentArtifacts, testingArtifacts, planArtifacts, execArtifacts, otherArtifacts]);

  const flatItems = useMemo(() => {
    const items: FlatArtifactItem[] = [];
    allSections.forEach((section, sectionIdx) => {
      items.push({ type: "header", data: section, index: items.length });
      section.items.forEach((artifact) => {
        items.push({ type: "item", data: artifact, index: items.length });
      });
    });
    return items;
  }, [allSections]);

  // TanStack Virtual intentionally returns imperative helpers; React Compiler cannot memoize it safely.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: flatItems.length,
    getScrollElement: () => parentRef.current,
    estimateSize: (index) => {
      const item = flatItems[index];
      if (!item) return 60;
      return item.type === "header" ? 40 : expandedId === item.data.id ? 300 : 60;
    },
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
    <div className={cn("flex flex-col h-full overflow-hidden", isFullscreen && "fixed inset-0 z-50 bg-background")}>
      <div className="p-5 border-b border-border-subtle bg-surface/50 shrink-0">
        <div className="flex items-center justify-between">
          <h2 className="text-[10px] font-black uppercase tracking-[0.25em] text-text-muted">
            {t("artifacts.title")} ({artifacts.length})
          </h2>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setZoom(z => Math.max(50, z - 10))}
              className="p-1.5 rounded-lg hover:bg-surface-raised transition-colors"
              aria-label={t("ui.zoomOut")}
            >
              <ZoomOut size={14} className="text-text-muted" />
            </button>
            <span className="text-[10px] font-mono text-text-muted w-10 text-center">{zoom}%</span>
            <button
              onClick={() => setZoom(z => Math.min(200, z + 10))}
              className="p-1.5 rounded-lg hover:bg-surface-raised transition-colors"
              aria-label={t("ui.zoomIn")}
            >
              <ZoomIn size={14} className="text-text-muted" />
            </button>
            <div className="w-px h-4 bg-border-subtle mx-1" />
            <button
              onClick={() => setWordWrap(w => !w)}
              className={cn("p-1.5 rounded-lg transition-colors", wordWrap ? "bg-surface-raised" : "hover:bg-surface-raised")}
              aria-label={t("ui.toggleWordWrap")}
            >
              <WrapText size={14} className={cn("text-text-muted", wordWrap && "text-brand")} />
            </button>
            <button
              onClick={() => setIsFullscreen(f => !f)}
              className="p-1.5 rounded-lg hover:bg-surface-raised transition-colors"
              aria-label={isFullscreen ? t("ui.exitFullscreen") : t("ui.enterFullscreen")}
            >
              {isFullscreen ? <Minimize2 size={14} className="text-text-muted" /> : <Maximize2 size={14} className="text-text-muted" />}
            </button>
          </div>
        </div>
      </div>

      <div ref={parentRef} className="flex-1 overflow-y-auto" style={{ maxHeight: isFullscreen ? "calc(100vh - 60px)" : maxHeight }}>
        <div
          style={{ height: `${virtualizer.getTotalSize()}px`, width: "100%", position: "relative" }}
        >
          {virtualizer.getVirtualItems().map((virtualRow) => {
            const item = flatItems[virtualRow.index];
            if (!item) return null;

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
                  zoom={zoom}
                  wordWrap={wordWrap}
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
  zoom = 100,
  wordWrap = true,
}: {
  artifact: Artifact;
  isExpanded: boolean;
  onToggle: () => void;
  zoom?: number;
  wordWrap?: boolean;
}) {
  const label = artifact.name || artifact.kind;
  const language = detectLanguage(
    typeof artifact.content === "string" ? artifact.content : JSON.stringify(artifact.content, null, 2),
    artifact.name
  );

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
          <span className="text-[9px] font-mono uppercase text-text-muted/50 bg-surface-raised px-1.5 py-0.5 rounded border border-border-subtle">
            {language}
          </span>
          {artifact.created_at && (
            <span className="text-[9px] text-text-muted/50 font-mono">
              {formatRelativeTime(artifact.created_at)}
            </span>
          )}
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
              {typeof artifact.content === "string" ? (
                <HighlightedCode code={artifact.content} language={language} zoom={zoom} wordWrap={wordWrap} />
              ) : (
                <HighlightedCode code={JSON.stringify(artifact.content, null, 2)} language="json" zoom={zoom} wordWrap={wordWrap} />
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
