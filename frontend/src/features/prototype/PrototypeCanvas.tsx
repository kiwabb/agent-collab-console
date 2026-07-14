"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Clock3, Code2, Eye, FileCode2, History, Route, Send, Trash2 } from "lucide-react";

import { deletePrototype, getPrototypeStreamUrl, getPrototypeVersion } from "@/lib/api/prototypes";
import type { Prototype, PrototypeVersion } from "@/lib/types";
import { useI18n } from "@/providers/I18nProvider";
import { useToast } from "@/components/ui/toast";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Loader } from "@/components/ui/loader";
import { cn } from "@/lib/utils";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { PreviewFrame } from "./PreviewFrame";
import type { PrototypeRouteTarget } from "./prototypeNavigation";
import { parseSseRecord, readSseNumber, readSseString } from "./prototypeStreamEvents";

interface Props {
  prototype: Prototype;
  versions: PrototypeVersion[];
  routeTargets: PrototypeRouteTarget[];
  activeRoutePattern: string | null;
  onNavigate: (route: string) => void;
  onVersionsChanged: () => void;
  onPrototypeDeleted: () => void;
}

interface StreamState {
  /** Accumulated HTML chunks received from the SSE `delta` events. */
  streamingHtml: string;
  /** LLM model announced in the SSE `meta` event (or null while pending). */
  model: string | null;
  /** True between connect and `done`/`error`. */
  streaming: boolean;
  /** Latest error message if the stream failed; cleared on next attempt. */
  errorMessage: string | null;
}

const INITIAL_STREAM: StreamState = {
  streamingHtml: "",
  model: null,
  streaming: false,
  errorMessage: null,
};

/**
 * Renders the live canvas for one Prototype:
 *   - Brief/instruction input
 *   - "Generate" (v1) / "Iterate" (vN+1) button that drives the SSE stream
 *   - Side-by-side preview (sandboxed iframe) + code (monospaced view)
 *   - Version picker at the bottom for jumping back to old versions
 *
 * SSE lifecycle:
 *   - The EventSource auto-reconnects on network errors. We add a
 *     `?instruction=...` query string when iterating and rely on the
 *     server to deliver `meta` → `delta*` → `done` | `error`.
 *   - We close the source manually once we see `done` or `error` so the
 *     browser doesn't keep the connection open after we're done.
 *   - On unmount we always close the source so an in-flight stream
 *     doesn't outlive the component (matters when the user picks a
 *     different prototype in the sidebar).
 */
export function PrototypeCanvas({
  prototype,
  versions,
  routeTargets,
  activeRoutePattern,
  onNavigate,
  onVersionsChanged,
  onPrototypeDeleted,
}: Props) {
  const { locale, t } = useI18n();
  const { addToast } = useToast();

  const [iteration, setIteration] = useState("");
  const [stream, setStream] = useState<StreamState>(INITIAL_STREAM);
  const [activeVersion, setActiveVersion] = useState<number>(prototype.current_version);
  const [historicalHtml, setHistoricalHtml] = useState<string | null>(null);
  const [historicalLoading, setHistoricalLoading] = useState(false);

  const sourceRef = useRef<EventSource | null>(null);

  const orderedVersions = useMemo(
    () => [...versions].sort((a, b) => a.version_no - b.version_no),
    [versions],
  );

  // Pick the most recent version whenever versions/current_version change,
  // unless the user has explicitly navigated away.
  useEffect(() => {
    if (prototype.current_version > 0 && activeVersion === 0) {
      setActiveVersion(prototype.current_version);
    }
  }, [prototype.current_version, activeVersion]);

  // Cancel any in-flight stream on unmount or when switching prototype.
  useEffect(() => {
    return () => {
      if (sourceRef.current) {
        sourceRef.current.close();
        sourceRef.current = null;
      }
    };
  }, [prototype.id]);

  // When the active version changes, load its HTML body.
  useEffect(() => {
    let cancelled = false;
    if (stream.streaming) {
      // Don't fetch historical HTML while a stream is in flight — the
      // streaming accumulator IS the HTML we want to show.
      return;
    }
    if (activeVersion <= 0) {
      setHistoricalHtml(null);
      return;
    }
    setHistoricalLoading(true);
    getPrototypeVersion(prototype.id, activeVersion)
      .then((res) => {
        if (cancelled) return;
        setHistoricalHtml(res.html);
      })
      .catch((err) => {
        if (cancelled) return;
        addToast({
          type: "error",
          title: t("prototype.toast.versionLoadFailed"),
          message: err instanceof Error ? err.message : String(err),
        });
      })
      .finally(() => {
        if (!cancelled) setHistoricalLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeVersion, prototype.id, stream.streaming, addToast, t]);

  const runStream = useCallback(
    (instruction: string | undefined) => {
      // Make sure any previous stream is closed before opening a new one —
      // browsers are happy to let two EventSources for the same URL coexist
      // but the second connection would race with the first on `done`.
      if (sourceRef.current) {
        sourceRef.current.close();
        sourceRef.current = null;
      }
      const url = getPrototypeStreamUrl(prototype.id, instruction);
      setStream({ streamingHtml: "", model: null, streaming: true, errorMessage: null });
      const source = new EventSource(url);
      sourceRef.current = source;
      source.addEventListener("meta", (ev) => {
        const data = parseSseRecord(ev);
        if (!data) return;
        const model = readSseString(data, "model");
        setStream((s) => ({ ...s, model: model ?? s.model }));
      });
      source.addEventListener("delta", (ev) => {
        const data = parseSseRecord(ev);
        if (!data) return;
        const chunk = readSseString(data, "chunk");
        if (chunk) {
          setStream((s) => ({ ...s, streamingHtml: s.streamingHtml + chunk }));
        }
      });
      source.addEventListener("done", (ev) => {
        const data = parseSseRecord(ev);
        const versionNo = data ? readSseNumber(data, "version_no") : null;
        source.close();
        if (sourceRef.current === source) sourceRef.current = null;
        setStream((s) => ({ ...s, streaming: false }));
        if (versionNo === null) return;
        setActiveVersion(versionNo);
        setHistoricalHtml(null); // clear stale view; useEffect reloads
        onVersionsChanged();
      });
      source.addEventListener("error", (ev) => {
        // EventSource fires `error` both on transport failures and on
        // custom server-side `event: error` messages. We try to parse
        // `data`; if there's no payload we assume transport and just stop.
        const data = parseSseRecord(ev);
        const message = data ? readSseString(data, "message") : null;
        setStream((s) => ({
          ...s,
          streaming: false,
          errorMessage: data ? (message ?? "stream error") : null,
        }));
        source.close();
        if (sourceRef.current === source) sourceRef.current = null;
      });
    },
    [prototype.id, onVersionsChanged],
  );

  const handleGenerate = useCallback(() => {
    if (!iteration.trim() && prototype.current_version > 0) {
      addToast({
        type: "info",
        title: t("prototype.iterateHint"),
        message: t("prototype.iteratePlaceholder"),
      });
      return;
    }
    runStream(iteration.trim() || undefined);
  }, [iteration, prototype.current_version, runStream, addToast, t]);

  const handleDelete = useCallback(async () => {
    if (!window.confirm(t("prototype.deleteConfirm"))) return;
    try {
      await deletePrototype(prototype.id);
      onPrototypeDeleted();
    } catch (err) {
      addToast({
        type: "error",
        title: t("prototype.toast.deleteFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }, [prototype.id, onPrototypeDeleted, addToast, t]);

  const displayHtml = stream.streaming ? stream.streamingHtml : (historicalHtml ?? "");
  const previewKey = stream.streaming ? "streaming" : `v${activeVersion}`;
  const updatedAt = useMemo(
    () =>
      prototype.updated_at
        ? new Intl.DateTimeFormat(locale, {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
          }).format(new Date(prototype.updated_at))
        : t("prototype.updatedUnknown"),
    [locale, prototype.updated_at, t],
  );

  return (
    <div className="grid min-h-0 min-w-0 flex-1 gap-3 xl:grid-cols-[minmax(0,1fr)_18rem]">
      <section className="flex min-h-0 min-w-0 flex-col">
        <header className="mb-2 flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <h2 className="truncate text-lg font-semibold">{prototype.title}</h2>
              <Badge variant="outline">
                {prototype.source_kind === "code" ? <Code2 size={12} /> : <FileCode2 size={12} />}
                {t(`prototype.source.${prototype.source_kind}`)}
              </Badge>
              {stream.streaming && (
                <Badge variant="secondary">{t("prototype.streamingLabel")}</Badge>
              )}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-text-muted">
              <span className="flex items-center gap-1">
                <History size={12} aria-hidden="true" />
                {t("prototype.currentVersion", { version: prototype.current_version })}
              </span>
              <span className="flex items-center gap-1">
                <Clock3 size={12} aria-hidden="true" />
                {t("prototype.updatedAt", { time: updatedAt })}
              </span>
            </div>
          </div>
        </header>

        <Tabs defaultValue="preview" className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="mb-2 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <TabsList className="h-11 self-start sm:h-8">
              <TabsTrigger className="min-h-11 min-w-24 sm:min-h-0" value="preview">
                <Eye size={14} />
                {t("prototype.previewLabel")}
              </TabsTrigger>
              <TabsTrigger className="min-h-11 min-w-24 sm:min-h-0" value="code">
                <Code2 size={14} />
                {t("prototype.codeLabel")}
              </TabsTrigger>
            </TabsList>
            {routeTargets.length > 0 && (
              <div className="flex min-w-0 items-center gap-2">
                <Route className="shrink-0 text-text-muted" size={14} aria-hidden="true" />
                <Select
                  value={activeRoutePattern ?? ""}
                  onValueChange={(value) => {
                    if (value) onNavigate(value);
                  }}
                >
                  <SelectTrigger
                    className="h-11 min-w-0 flex-1 font-mono sm:h-8 sm:w-72 sm:flex-none"
                    aria-label={t("prototype.projectRoute")}
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {routeTargets.map((target) => (
                      <SelectItem
                        key={`${target.prototypeId}:${target.routePattern}`}
                        value={target.routePattern}
                      >
                        <span className="font-mono">{target.routePattern}</span>
                        <span className="truncate text-text-muted">{target.title}</span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>

          <TabsContent value="preview" className="min-h-0 min-w-0 flex-1">
            <div className="relative h-[70dvh] min-h-[30rem] max-h-[54rem] overflow-hidden rounded-lg border border-border-subtle bg-surface-raised lg:h-[68vh]">
              {historicalLoading && !stream.streaming ? (
                <div className="flex h-full items-center justify-center">
                  <Loader variant="card" label={t("prototype.loading")} />
                </div>
              ) : displayHtml ? (
                <PreviewFrame html={displayHtml} versionKey={previewKey} onNavigate={onNavigate} />
              ) : (
                <div className="flex h-full items-center justify-center px-6 text-center text-sm text-text-muted">
                  {t("prototype.noVersionsYet")}
                </div>
              )}
              {stream.streaming && (
                <div className="motion-essential pointer-events-none absolute inset-x-0 top-0 h-[2px] animate-shimmer-sweep bg-brand" />
              )}
            </div>
          </TabsContent>

          <TabsContent value="code" className="min-h-0 min-w-0 flex-1">
            <pre
              className={cn(
                "h-[70dvh] min-h-[30rem] max-h-[54rem] overflow-auto rounded-lg border border-border-subtle bg-surface-base p-4 lg:h-[68vh]",
                "font-mono text-xs leading-relaxed text-foreground",
              )}
            >
              {displayHtml || t("prototype.noVersionsYet")}
            </pre>
          </TabsContent>
        </Tabs>
      </section>

      <aside className="min-w-0 border-t border-border-subtle pt-3 xl:border-l xl:border-t-0 xl:pl-3 xl:pt-0">
        <section className="border-b border-border-subtle pb-4">
          <div className="flex items-center justify-between gap-2">
            <h3 className="flex items-center gap-2 text-sm font-semibold">
              <History size={15} aria-hidden="true" />
              {t("prototype.versionsLabel")}
            </h3>
            <span className="font-mono text-xs text-text-muted">
              {activeVersion}/{prototype.current_version}
            </span>
          </div>
          {orderedVersions.length > 0 ? (
            <nav aria-label={t("prototype.versionsLabel")} className="mt-3 flex flex-wrap gap-2">
              {orderedVersions.map((version) => (
                <button
                  key={version.id}
                  type="button"
                  onClick={() => setActiveVersion(version.version_no)}
                  aria-current={activeVersion === version.version_no ? "true" : undefined}
                  className={cn(
                    "min-h-11 min-w-11 rounded-md border px-3 py-1 text-xs font-semibold transition-colors xl:min-h-8",
                    activeVersion === version.version_no
                      ? "border-brand bg-brand/15 text-foreground"
                      : "border-border-subtle bg-surface-base text-text-muted hover:text-foreground",
                  )}
                >
                  v{version.version_no}
                </button>
              ))}
            </nav>
          ) : (
            <p className="mt-2 text-xs text-text-muted">{t("prototype.noVersionsYet")}</p>
          )}
        </section>

        <section className="border-b border-border-subtle py-4">
          <h3 className="text-sm font-semibold">{t("prototype.iterationTitle")}</h3>
          <Textarea
            className="mt-3 min-h-28"
            rows={5}
            value={iteration}
            onChange={(event) => setIteration(event.target.value)}
            placeholder={
              prototype.current_version > 0
                ? t("prototype.iteratePlaceholder")
                : t("prototype.briefPlaceholder")
            }
            disabled={stream.streaming}
          />
          <Button
            className="mt-3 min-h-11 w-full xl:min-h-8"
            onClick={handleGenerate}
            disabled={stream.streaming}
          >
            <Send size={14} />
            {stream.streaming
              ? t("prototype.streamingLabel")
              : prototype.current_version > 0
                ? t("prototype.iterateButton")
                : t("prototype.generateButton")}
          </Button>
          {stream.model && (
            <p className="mt-2 truncate font-mono text-xs text-text-muted">{stream.model}</p>
          )}
        </section>

        {stream.errorMessage && (
          <div
            role="alert"
            className="border-b border-status-failed/40 py-3 text-xs text-status-failed [overflow-wrap:anywhere]"
          >
            {stream.errorMessage}
          </div>
        )}

        <section className="pt-4">
          <Button
            variant="destructive"
            size="sm"
            onClick={handleDelete}
            className="min-h-11 w-full xl:min-h-8"
          >
            <Trash2 size={14} />
            {t("prototype.deleteButton")}
          </Button>
        </section>
      </aside>
    </div>
  );
}
