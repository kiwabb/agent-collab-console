"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  getPrototypeStreamUrl,
  getPrototypeVersion,
} from "@/lib/api";
import type { Prototype, PrototypeVersion } from "@/lib/types";
import { useI18n } from "@/providers/I18nProvider";
import { useToast } from "@/components/ui/toast";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Loader } from "@/components/ui/loader";
import { cn } from "@/lib/utils";

import { PreviewFrame } from "./PreviewFrame";

interface Props {
  projectId: string;
  prototype: Prototype;
  versions: PrototypeVersion[];
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
  onVersionsChanged,
  onPrototypeDeleted,
}: Props) {
  const { t } = useI18n();
  const { addToast } = useToast();

  const [iteration, setIteration] = useState("");
  const [stream, setStream] = useState<StreamState>(INITIAL_STREAM);
  const [activeVersion, setActiveVersion] = useState<number>(
    prototype.current_version,
  );
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
        setHistoricalHtml(null);
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
        try {
          const data = JSON.parse((ev as MessageEvent).data) as { model?: string };
          setStream((s) => ({ ...s, model: data.model ?? s.model }));
        } catch {
          // Tolerate malformed meta — model stays null, otherwise harmless.
        }
      });
      source.addEventListener("delta", (ev) => {
        try {
          const data = JSON.parse((ev as MessageEvent).data) as { chunk?: string };
          if (data.chunk) {
            setStream((s) => ({ ...s, streamingHtml: s.streamingHtml + data.chunk }));
          }
        } catch {
          // Drop malformed chunk; stream continues.
        }
      });
      source.addEventListener("done", (ev) => {
        try {
          const data = JSON.parse((ev as MessageEvent).data) as { version_no: number };
          source.close();
          if (sourceRef.current === source) sourceRef.current = null;
          setStream((s) => ({ ...s, streaming: false }));
          setActiveVersion(data.version_no);
          setHistoricalHtml(null); // clear stale view; useEffect reloads
          onVersionsChanged();
        } catch {
          source.close();
          if (sourceRef.current === source) sourceRef.current = null;
          setStream((s) => ({ ...s, streaming: false }));
        }
      });
      source.addEventListener("error", (ev) => {
        // EventSource fires `error` both on transport failures and on
        // custom server-side `event: error` messages. We try to parse
        // `data`; if there's no payload we assume transport and just stop.
        try {
          const messageEvent = ev as MessageEvent;
          if (messageEvent && typeof messageEvent.data === "string" && messageEvent.data) {
            const data = JSON.parse(messageEvent.data) as { message?: string };
            setStream((s) => ({
              ...s,
              streaming: false,
              errorMessage: data.message ?? "stream error",
            }));
          } else {
            setStream((s) => ({ ...s, streaming: false, errorMessage: null }));
          }
        } catch {
          setStream((s) => ({ ...s, streaming: false, errorMessage: null }));
        }
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
      const { deletePrototype } = await import("@/lib/api");
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

  const displayHtml = stream.streaming
    ? stream.streamingHtml
    : historicalHtml ?? "";
  const previewKey = stream.streaming ? "streaming" : `v${activeVersion}`;

  return (
    <div className="flex h-full flex-col gap-3">
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate text-xl font-semibold">{prototype.title}</h2>
          <p className="text-xs text-text-muted">
            {prototype.current_version > 0
              ? t("prototype.versionsLabel") + `: v${prototype.current_version}`
              : t("prototype.noVersionsYet")}
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleDelete}
          className="text-text-muted hover:text-status-failed"
        >
          {t("prototype.deleteButton")}
        </Button>
      </header>

      <Tabs defaultValue="preview" className="flex h-full min-h-0 flex-col">
        <TabsList>
          <TabsTrigger value="preview">{t("prototype.previewLabel")}</TabsTrigger>
          <TabsTrigger value="code">{t("prototype.codeLabel")}</TabsTrigger>
        </TabsList>

        <TabsContent value="preview" className="min-h-0 flex-1">
          <div className="relative h-full min-h-[420px] overflow-hidden rounded-xl border border-border-subtle bg-surface-raised">
            {historicalLoading && !stream.streaming ? (
              <div className="flex h-full items-center justify-center">
                <Loader variant="card" label="Loading…" />
              </div>
            ) : displayHtml ? (
              <PreviewFrame html={displayHtml} versionKey={previewKey} />
            ) : (
              <div className="flex h-full items-center justify-center px-6 text-center text-sm text-text-muted">
                {t("prototype.noVersionsYet")}
              </div>
            )}
            {stream.streaming && (
              <div className="pointer-events-none absolute inset-x-0 top-0 h-[2px] animate-shimmer-sweep bg-gradient-to-r from-transparent via-brand/70 to-transparent" />
            )}
          </div>
        </TabsContent>

        <TabsContent value="code" className="min-h-0 flex-1">
          <pre
            className={cn(
              "h-full min-h-[420px] overflow-auto rounded-xl border border-border-subtle bg-surface-base p-4",
              "font-mono text-xs leading-relaxed text-foreground",
            )}
          >
            {displayHtml || t("prototype.noVersionsYet")}
          </pre>
        </TabsContent>
      </Tabs>

      <footer className="flex flex-col gap-2 rounded-xl border border-border-subtle bg-surface-raised p-3">
        <Textarea
          rows={3}
          value={iteration}
          onChange={(e) => setIteration(e.target.value)}
          placeholder={
            prototype.current_version > 0
              ? t("prototype.iteratePlaceholder")
              : t("prototype.briefPlaceholder")
          }
          disabled={stream.streaming}
        />
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-text-muted">
            {prototype.current_version > 0
              ? t("prototype.iterateHint")
              : t("prototype.noVersionsYet")}
          </p>
          <Button onClick={handleGenerate} disabled={stream.streaming}>
            {stream.streaming
              ? t("prototype.streamingLabel")
              : prototype.current_version > 0
                ? t("prototype.iterateButton")
                : t("prototype.generateButton")}
          </Button>
        </div>
      </footer>

      {orderedVersions.length > 0 && (
        <nav
          aria-label={t("prototype.versionsLabel")}
          className="flex flex-wrap gap-2"
        >
          {orderedVersions.map((v) => (
            <button
              key={v.id}
              type="button"
              onClick={() => setActiveVersion(v.version_no)}
              className={cn(
                "rounded-full border px-3 py-1 text-xs font-semibold transition-colors",
                activeVersion === v.version_no
                  ? "border-brand bg-brand/15 text-foreground"
                  : "border-border-subtle bg-surface-raised text-text-muted hover:text-foreground",
              )}
            >
              v{v.version_no}
            </button>
          ))}
        </nav>
      )}

      {stream.errorMessage && (
        <div
          role="alert"
          className="rounded-lg border border-status-failed/40 bg-status-failed/10 px-3 py-2 text-xs text-status-failed"
        >
          {stream.errorMessage}
        </div>
      )}
    </div>
  );
}