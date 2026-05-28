"use client";

import { useEffect, useMemo, useState } from "react";
import { FileText, FileCode2, FileJson, FileType2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Artifact } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

interface Props {
  artifacts: Artifact[];
}

interface NormalArtifact {
  id: string;
  name: string;
  task_id: string | null;
  kind: string;
  content: string | null;
  created_at: string | null;
}

function normalize(a: Artifact): NormalArtifact {
  return {
    id: a.id,
    name: a.name ?? "(unnamed)",
    task_id: a.task_id ?? null,
    kind: a.kind ?? "",
    content: typeof a.content === "string" ? a.content : null,
    created_at: a.created_at ?? null,
  };
}

/**
 * Two-column layout mirroring the design handoff's artifacts tab:
 *   [ 280px file list | flex preview ]
 *
 * Left:  one row per artifact (kind-colored icon + name + producer + size)
 * Right: a sticky head bar (path / producer chip / actions) +
 *        a body that renders markdown via react-markdown, or shows the
 *        raw text for non-markdown content. Files we have no content for
 *        get a "binary or too large" placeholder.
 */
export function ArtifactsSplitView({ artifacts }: Props) {
  const { t } = useI18n();
  const sorted = useMemo<NormalArtifact[]>(
    () =>
      artifacts
        .map(normalize)
        .sort(
          (a, b) =>
            (a.created_at ?? "").localeCompare(b.created_at ?? "") ||
            a.name.localeCompare(b.name),
        ),
    [artifacts],
  );

  const [activeId, setActiveId] = useState<string | null>(
    sorted[0]?.id ?? null,
  );

  // Keep selection alive across refreshes; if the previously selected
  // artifact is no longer in the list (rare), pick the first.
  useEffect(() => {
    if (sorted.length === 0) {
      setActiveId(null);
      return;
    }
    if (!activeId || !sorted.some((a) => a.id === activeId)) {
      setActiveId(sorted[0].id);
    }
  }, [sorted, activeId]);

  const active = sorted.find((a) => a.id === activeId) ?? sorted[0] ?? null;

  if (sorted.length === 0) {
    return null;
  }

  return (
    <div className="grid grid-cols-[280px_minmax(0,1fr)] grid-rows-1 h-full min-h-0 border border-border-subtle rounded-2xl overflow-hidden">
      {/* === LEFT: file list === */}
      <ul className="border-r border-border-subtle overflow-y-auto py-1.5 bg-surface">
        {sorted.map((a) => {
          const kind = inferKind(a.name);
          return (
            <li key={a.id}>
              <button
                type="button"
                onClick={() => setActiveId(a.id)}
                className={cn(
                  "w-full grid grid-cols-[22px_minmax(0,1fr)_auto] items-center gap-2.5 px-3.5 py-2 text-left",
                  "border-l-2 transition-colors hover:bg-surface-hover",
                  a.id === active?.id
                    ? "bg-surface-hover border-brand"
                    : "border-transparent",
                )}
              >
                <KindIcon kind={kind} />
                <span className="min-w-0">
                  <span className="block text-[12.5px] font-medium text-foreground truncate leading-tight">
                    {basename(a.name)}
                  </span>
                  <span className="block font-mono text-[10.5px] text-text-faint mt-0.5 truncate">
                    {a.task_id
                      ? `${producerLabel(a)} · ${shortTime(a.created_at)}`
                      : shortTime(a.created_at)}
                  </span>
                </span>
                <span className="font-mono text-[10.5px] text-text-faint whitespace-nowrap">
                  {fmtSize(a.content)}
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      {/* === RIGHT: preview === */}
      <div className="flex flex-col min-w-0 min-h-0 bg-background/40">
        <PreviewHead artifact={active} copyLabel={t("issue.artifacts.previewCopy")} />
        <PreviewBody
          artifact={active}
          emptyText={t("issue.artifacts.previewEmpty")}
          binaryText={t("issue.artifacts.previewBinary")}
        />
      </div>
    </div>
  );
}

function PreviewHead({
  artifact,
  copyLabel,
}: {
  artifact: NormalArtifact | null;
  copyLabel: string;
}) {
  if (!artifact) return null;
  const dir = dirname(artifact.name);
  const file = basename(artifact.name);
  return (
    <div className="flex items-center justify-between gap-2.5 px-4 py-2.5 border-b border-border-subtle bg-surface">
      <div className="flex items-center gap-2.5 min-w-0">
        <KindIcon kind={inferKind(artifact.name)} small />
        <span className="font-mono text-[12.5px] text-foreground truncate font-medium">
          {dir && <span className="text-text-faint">{dir}/</span>}
          {file}
        </span>
        <span className="font-mono text-[10.5px] uppercase tracking-wider text-text-muted bg-surface-input border border-border-muted px-1.5 py-0.5 rounded">
          {producerLabel(artifact)}
        </span>
      </div>
      <div className="flex items-center gap-1.5 shrink-0">
        <HeaderAction
          label={copyLabel}
          onClick={() => {
            if (artifact.content && typeof navigator !== "undefined") {
              void navigator.clipboard.writeText(artifact.content);
            }
          }}
        />
      </div>
    </div>
  );
}

function PreviewBody({
  artifact,
  emptyText,
  binaryText,
}: {
  artifact: NormalArtifact | null;
  emptyText: string;
  binaryText: string;
}) {
  if (!artifact) {
    return (
      <div className="flex-1 grid place-items-center text-[12px] text-text-muted">
        {emptyText}
      </div>
    );
  }
  const content = artifact.content;
  if (content == null) {
    return (
      <div className="flex-1 grid place-items-center text-[12px] text-text-muted px-6 text-center">
        {binaryText}
      </div>
    );
  }
  const kind = inferKind(artifact.name);
  if (kind === "md") {
    return (
      <div
        className="flex-1 overflow-auto px-6 py-5 text-[13px] leading-relaxed text-text-secondary prose-overrides"
        style={{
          background:
            "linear-gradient(180deg, color-mix(in srgb, var(--color-surface-raised) 40%, transparent), transparent)",
        }}
      >
        <ArtifactMetaGrid artifact={artifact} />
        <div className="markdown-body">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              h1: ({ children }) => (
                <h1 className="text-[18px] font-black text-foreground mt-6 mb-3 first:mt-0 border-b border-border-subtle pb-1.5 leading-snug">
                  {children}
                </h1>
              ),
              h2: ({ children }) => (
                <h2 className="text-[16px] font-bold text-foreground mt-5 mb-2.5 first:mt-0 border-b border-border-subtle/50 pb-1 leading-snug">
                  {children}
                </h2>
              ),
              h3: ({ children }) => (
                <h3 className="text-[14px] font-bold text-brand mt-4 mb-2 leading-snug">
                  {children}
                </h3>
              ),
              h4: ({ children }) => (
                <h4 className="text-[12.5px] font-bold text-text-primary mt-3.5 mb-1.5 uppercase tracking-wider">
                  {children}
                </h4>
              ),
              p: ({ children }) => (
                <p className="my-2.5 text-[13px] leading-relaxed text-text-secondary">
                  {children}
                </p>
              ),
              ul: ({ children }) => (
                <ul className="pl-6 my-3 list-disc space-y-1.5 text-[13px] text-text-secondary">
                  {children}
                </ul>
              ),
              ol: ({ children }) => (
                <ol className="pl-6 my-3 list-decimal space-y-1.5 text-[13px] text-text-secondary">
                  {children}
                </ol>
              ),
              li: ({ children }) => (
                <li className="leading-relaxed pl-0.5">
                  {children}
                </li>
              ),
              blockquote: ({ children }) => (
                <blockquote className="pl-4 py-2 my-4 border-l-4 border-brand bg-brand-muted/10 rounded-r-xl text-text-secondary italic text-[13px] leading-relaxed">
                  {children}
                </blockquote>
              ),
              table: ({ children }) => (
                <div className="my-5 overflow-x-auto rounded-xl border border-border-subtle shadow-sm bg-surface/30">
                  <table className="w-full border-collapse text-left text-[12.5px] leading-normal">
                    {children}
                  </table>
                </div>
              ),
              thead: ({ children }) => (
                <thead className="bg-surface-raised border-b border-border-subtle text-[11px] font-black uppercase tracking-wider text-text-muted">
                  {children}
                </thead>
              ),
              tbody: ({ children }) => (
                <tbody className="divide-y divide-border-subtle bg-transparent">
                  {children}
                </tbody>
              ),
              tr: ({ children }) => (
                <tr className="hover:bg-surface-hover/30 transition-colors">
                  {children}
                </tr>
              ),
              th: ({ children }) => (
                <th className="px-4 py-3 font-semibold text-foreground">
                  {children}
                </th>
              ),
              td: ({ children }) => (
                <td className="px-4 py-2.5 text-text-secondary font-medium font-sans">
                  {children}
                </td>
              ),
              hr: () => (
                <hr className="my-6 border-t border-border-subtle" />
              ),
              a: ({ href, children }) => (
                <a
                  href={href}
                  target="_blank"
                  rel="noreferrer"
                  className="text-brand hover:text-brand-strong hover:underline font-semibold transition-all inline-flex items-center gap-0.5"
                >
                  {children}
                </a>
              ),
              code: ({ className, children }) => {
                const isBlock = className?.includes("language-");
                return isBlock ? (
                  <pre className="my-3 p-3.5 rounded-xl bg-surface-input border border-border-subtle overflow-auto font-mono text-[12px] leading-relaxed shadow-inner">
                    <code>{children}</code>
                  </pre>
                ) : (
                  <code className="font-mono text-[11.5px] bg-surface-input border border-border-subtle px-1.5 py-0.5 rounded text-brand-strong font-medium">
                    {children}
                  </code>
                );
              },
              strong: ({ children }) => (
                <strong className="text-foreground font-black">
                  {children}
                </strong>
              ),
            }}
          >
            {content}
          </ReactMarkdown>
        </div>
      </div>
    );
  }
  return (
    <div className="flex-1 overflow-auto px-6 py-5 bg-background">
      <ArtifactMetaGrid artifact={artifact} />
      <pre className="font-mono text-[12px] leading-relaxed text-text-secondary whitespace-pre-wrap break-words">
        {content}
      </pre>
    </div>
  );
}

function ArtifactMetaGrid({ artifact }: { artifact: NormalArtifact }) {
  return (
    <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3.5 gap-y-1 font-mono text-[11.5px] text-text-muted mb-3 px-3 py-2.5 bg-surface-raised border border-border-subtle rounded-lg">
      <span className="text-text-faint">producer</span>
      <span className="text-text-secondary">{producerLabel(artifact)}</span>
      {artifact.created_at && (
        <>
          <span className="text-text-faint">created</span>
          <span className="text-text-secondary">
            {new Date(artifact.created_at).toLocaleString()}
          </span>
        </>
      )}
      <span className="text-text-faint">path</span>
      <span className="text-text-secondary truncate">{artifact.name}</span>
      <span className="text-text-faint">size</span>
      <span className="text-text-secondary">
        {fmtSize(artifact.content)}
        {artifact.content
          ? ` · ${artifact.content.split("\n").length} lines`
          : ""}
      </span>
    </div>
  );
}

function HeaderAction({
  label,
  onClick,
}: {
  label: string;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="h-7 px-2.5 text-[12px] rounded-md border border-border-muted bg-surface-raised text-text-secondary hover:text-foreground hover:bg-surface-input hover:border-border-strong"
    >
      {label}
    </button>
  );
}

type Kind = "md" | "yaml" | "json" | "py" | "code" | "other";

function inferKind(name: string): Kind {
  const lower = name.toLowerCase();
  if (lower.endsWith(".md") || lower.endsWith(".mdx")) return "md";
  if (lower.endsWith(".yaml") || lower.endsWith(".yml")) return "yaml";
  if (lower.endsWith(".json")) return "json";
  if (lower.endsWith(".py")) return "py";
  if (/\.(ts|tsx|js|jsx|css|html|sql|sh|go|rs|java|c|cpp)$/.test(lower))
    return "code";
  return "other";
}

function KindIcon({ kind, small }: { kind: Kind; small?: boolean }) {
  const size = small ? 12 : 12;
  const wrapperSize = small ? 18 : 22;
  const palette = (() => {
    switch (kind) {
      case "md":
        return {
          color: "var(--color-status-info)",
          bg: "var(--color-info-bg)",
        };
      case "yaml":
        return {
          color: "var(--color-status-tool)",
          bg: "var(--color-tool-bg)",
        };
      case "json":
        return {
          color: "var(--color-status-awaiting)",
          bg: "var(--color-warning-bg)",
        };
      case "py":
      case "code":
        return {
          color: "var(--color-status-done)",
          bg: "var(--color-done-bg)",
        };
      default:
        return {
          color: "var(--color-text-muted)",
          bg: "var(--color-surface-input)",
        };
    }
  })();
  const Icon =
    kind === "md"
      ? FileText
      : kind === "yaml"
        ? FileType2
        : kind === "json"
          ? FileJson
          : kind === "py" || kind === "code"
            ? FileCode2
            : FileText;
  return (
    <span
      className="rounded-md flex items-center justify-center shrink-0"
      style={{
        width: wrapperSize,
        height: wrapperSize,
        background: palette.bg,
        color: palette.color,
      }}
    >
      <Icon size={size} strokeWidth={2} />
    </span>
  );
}

function basename(path: string): string {
  const slash = path.lastIndexOf("/");
  return slash >= 0 ? path.slice(slash + 1) : path;
}

function dirname(path: string): string {
  const slash = path.lastIndexOf("/");
  return slash > 0 ? path.slice(0, slash) : "";
}

function shortTime(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  } catch {
    return "";
  }
}

function fmtSize(content: string | null | undefined): string {
  if (content == null) return "";
  const bytes = new Blob([content]).size;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function producerLabel(a: NormalArtifact): string {
  if (a.kind && /^(pm|product_manager|architect|engineer|qa)/i.test(a.kind)) {
    return a.kind.toUpperCase();
  }
  if (a.name.startsWith("pm/")) return "PM";
  if (a.name.startsWith("architect/")) return "Architect";
  if (a.name.startsWith("engineer/")) return "Engineer";
  if (a.name.startsWith("qa/")) return "QA";
  return a.kind || "artifact";
}
