"use client";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Bottom-pinned "Approval requested" card matching the reference shot.
 *
 *   ● Approval requested                                    step 7/9
 *   Run npm install in frontend/ to add jittered-backoff dependency?
 *   [ Approve · ⌘↵ ]                            [ Deny ] [ Edit ]
 */

interface Props {
  title?: string;
  /** Body text (can include inline <code> tags). */
  body: React.ReactNode;
  /** e.g. "step 7/9" */
  meta?: string;
  onApprove?: () => void;
  onDeny?: () => void;
  onEdit?: () => void;
  className?: string;
}

export function ApprovalCard({
  title = "Approval requested",
  body,
  meta,
  onApprove,
  onDeny,
  onEdit,
  className,
}: Props) {
  return (
    <div
      className={cn(
        "relative rounded-lg border border-brand/40 bg-brand/[0.04]",
        "p-3 flex flex-col gap-2",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-brand">
          <span className="size-1.5 rounded-full bg-brand" />
          {title}
        </span>
        {meta && <span className="text-[11px] text-text-muted font-mono">{meta}</span>}
      </div>
      <div className="text-sm leading-relaxed text-foreground">{body}</div>
      <div className="flex items-center gap-2 pt-1">
        <Button
          variant="default"
          size="sm"
          onClick={onApprove}
          className="flex-1 bg-brand hover:bg-brand-strong text-black font-semibold"
        >
          Approve · ⌘↵
        </Button>
        <Button variant="outline" size="sm" onClick={onDeny}>
          Deny
        </Button>
        <Button variant="ghost" size="sm" onClick={onEdit}>
          Edit
        </Button>
      </div>
    </div>
  );
}
