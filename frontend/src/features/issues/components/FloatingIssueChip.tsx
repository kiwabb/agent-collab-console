"use client";

import { useState } from "react";
import Link from "next/link";

interface Props {
  /** Last 1-2 chars of the issue id (e.g. "N" for nominal). Falls back to "I". */
  badge?: string;
  /** Where the chip links to. Default: stays on current page. */
  href?: string;
}

/**
 * The orange "1 Issue" pill in the design handoff's bottom-left corner.
 * Dismissible — the close click hides it for the session (no persistence,
 * the chip reappears next page load).
 */
export function FloatingIssueChip({ badge = "I", href }: Props) {
  const [dismissed, setDismissed] = useState(false);
  if (dismissed) return null;

  const Inner = (
    <span className="inline-flex items-center gap-2">
      <span
        className="size-[22px] rounded-full inline-flex items-center justify-center font-mono text-[11px]"
        style={{ background: "rgba(0,0,0,0.18)", color: "#1a0e05" }}
      >
        {badge.slice(0, 1).toUpperCase()}
      </span>
      <span>1 Issue</span>
    </span>
  );

  return (
    <div
      className="fixed left-4 bottom-9 z-10 inline-flex items-center gap-2 px-2 py-1.5 rounded-full font-semibold text-[12px]"
      style={{
        background: "var(--color-brand)",
        color: "#1a0e05",
        boxShadow: "0 8px 24px -6px var(--color-brand-ring)",
      }}
    >
      {href ? (
        <Link href={href} className="inline-flex items-center">
          {Inner}
        </Link>
      ) : (
        Inner
      )}
      <button
        type="button"
        onClick={() => setDismissed(true)}
        aria-label="dismiss"
        className="ml-1 opacity-70 hover:opacity-100"
      >
        ✕
      </button>
    </div>
  );
}
