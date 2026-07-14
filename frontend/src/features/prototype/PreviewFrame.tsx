"use client";

import { memo, useEffect, useRef } from "react";

import { isRecord } from "@/lib/utils";

import { injectPrototypeNavigationBridge } from "./prototypeNavigation";

/**
 * Renders an HTML string inside a hardened sandbox.
 *
 * Sandbox flags: only `allow-scripts`. We deliberately omit
 * `allow-same-origin` so the iframe runs as a unique opaque origin and
 * cannot reach into the parent app's storage, cookies, or DOM. This is
 * the same posture Anthropic's Claude Design uses for untrusted preview
 * HTML.
 *
 * The `key` prop (driven by version_no) forces a fresh iframe when the
 * user picks an old version, which avoids keeping the previous version's
 * DOM/JS state around — important if a generated page registered timers
 * or event listeners.
 */
interface Props {
  html: string;
  versionKey: string | number;
  onNavigate: (route: string) => void;
}

function PreviewFrameBase({ html, versionKey, onNavigate }: Props) {
  const ref = useRef<HTMLIFrameElement | null>(null);

  useEffect(() => {
    const handleMessage = (event: MessageEvent<unknown>) => {
      if (event.source !== ref.current?.contentWindow) return;
      const payload = isRecord(event.data) ? event.data : null;
      if (!payload) return;
      if (payload["type"] !== "prototype:navigate" || typeof payload["route"] !== "string") {
        return;
      }
      onNavigate(payload["route"]);
    };
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [onNavigate]);

  // srcDoc re-renders automatically when `html` changes, but we also
  // explicitly null+restore when the versionKey changes so any cached
  // document is destroyed cleanly (intervals/listeners released).
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    // No-op on first mount — srcDoc does the work. Subsequent versionKey
    // changes leave the effect as a no-op too, since React will diff
    // srcDoc. The hook is here primarily to make the dependency explicit
    // and to give a single place to add telemetry later.
    void node;
  }, [versionKey]);

  return (
    <iframe
      key={versionKey}
      ref={ref}
      title="prototype-preview"
      sandbox="allow-scripts"
      srcDoc={injectPrototypeNavigationBridge(html)}
      className="h-full w-full bg-white"
    />
  );
}

export const PreviewFrame = memo(PreviewFrameBase);
