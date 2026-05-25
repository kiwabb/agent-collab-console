"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, MessageSquareQuote, RefreshCw } from "lucide-react";
import { getAgentMessages, type AgentMessage } from "@/lib/api";
import { useBusEventEffect, busEventMatchers } from "@/hooks/useBusEventEffect";
import { cn } from "@/lib/utils";

const ROLE_LABEL: Record<string, string> = {
  conductor: "Conductor",
  product_manager: "PM",
  architect: "Architect",
  engineer: "Engineer",
  engineer_frontend: "FE Engineer",
  engineer_backend: "BE Engineer",
  qa: "QA",
  "specialist:security_reviewer": "🔒 Security Reviewer",
  "specialist:performance_reviewer": "⚡ Performance Reviewer",
  "specialist:doc_writer": "📚 Doc Writer",
  "specialist:code_reviewer": "👁️ Code Reviewer",
  "specialist:migration_planner": "🚀 Migration Planner",
  "specialist:dependency_auditor": "📦 Dependency Auditor",
  "specialist:api_contract_checker": "📋 API Contract Checker",
  "specialist:accessibility_reviewer": "♿ Accessibility Reviewer",
  "specialist:i18n_checker": "🌍 i18n Checker",
  "specialist:log_summarizer": "📊 Log Summarizer",
};


const TYPE_CONFIG: Record<
  AgentMessage["message_type"],
  { label: string; colorClass: string; borderClass: string; bgClass: string }
> = {
  critique: {
    label: "Critique",
    colorClass: "text-status-failed",
    borderClass: "border-l-status-failed",
    bgClass: "bg-surface-raised",
  },
  handoff: {
    label: "Handoff",
    colorClass: "text-status-done",
    borderClass: "border-l-status-done",
    bgClass: "bg-surface-raised",
  },
  clarification: {
    label: "Question",
    colorClass: "text-brand",
    borderClass: "border-l-brand",
    bgClass: "bg-surface-raised",
  },
  answer: {
    label: "Answer",
    colorClass: "text-text-secondary",
    borderClass: "border-l-border-muted",
    bgClass: "bg-surface-raised",
  },
  specialist_call: {
    label: "Specialist Call",
    colorClass: "text-blue-500",
    borderClass: "border-l-blue-500",
    bgClass: "bg-blue-50",
  },
  specialist_result: {
    label: "Specialist Result",
    colorClass: "text-blue-700",
    borderClass: "border-l-blue-700",
    bgClass: "bg-blue-100",
  },
};

interface Props {
  issueId: string;
  active: boolean;
}

export function CollabFeedTab({ issueId, active }: Props) {
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const msgs = await getAgentMessages(issueId);
      setMessages(msgs);
    } finally {
      setLoading(false);
    }
  }, [issueId]);

  useEffect(() => {
    if (active) void load();
  }, [active, load]);

  // Auto-scroll to bottom when new messages arrive.
  useEffect(() => {
    if (messages.length > 0) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages.length]);

  // Real-time refresh when an agent message is posted.
  useBusEventEffect({
    match: busEventMatchers.all(
      busEventMatchers.issueId(issueId),
      busEventMatchers.typeIn("agent_message_posted"),
    ),
    onEvent: () => { void load(); },
    throttleMs: 200,
  });

  if (!active) return null;

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border-subtle shrink-0">
        <div className="flex items-center gap-2 text-[12px] text-text-muted">
          <MessageSquareQuote size={13} />
          <span>Agent inter-communications</span>
          {messages.length > 0 && (
            <span className="font-mono text-[11px] bg-surface-input border border-border-subtle rounded px-1.5 py-0.5">
              {messages.length}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="text-text-muted hover:text-foreground transition-colors"
          title="Refresh"
        >
          <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {/* Feed */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {messages.length === 0 && !loading && (
          <div className="flex flex-col items-center justify-center h-40 text-center text-text-muted text-[12px] gap-2">
            <MessageSquareQuote size={28} strokeWidth={1.2} className="opacity-30" />
            <span>No inter-agent messages yet.</span>
            <span className="text-[11px] opacity-60">
              Critiques, handoffs, and clarifications between agents will appear here.
            </span>
          </div>
        )}

        {messages.map((msg) => {
          const cfg = TYPE_CONFIG[msg.message_type] ?? TYPE_CONFIG.handoff;
          const fromLabel = ROLE_LABEL[msg.from_node_key] ?? msg.from_node_key;
          const toLabel = ROLE_LABEL[msg.to_node_key] ?? msg.to_node_key;
          const ts = msg.created_at
            ? new Date(msg.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
            : null;

          return (
            <div
              key={msg.id}
              className={cn(
                "rounded-lg border border-border-subtle border-l-2 px-3 py-2.5",
                cfg.borderClass,
                cfg.bgClass,
              )}
            >
              {/* Header row: from → to + type badge + timestamp */}
              <div className="flex items-center gap-1.5 mb-1.5 text-[11px]">
                <span className="font-mono font-semibold text-foreground">{fromLabel}</span>
                <ArrowRight size={10} className="text-text-faint shrink-0" />
                <span className="font-mono font-semibold text-foreground">{toLabel}</span>
                <span
                  className={cn(
                    "ml-1 px-1.5 py-0.5 rounded font-mono text-[10px] font-semibold uppercase tracking-wide border border-current/20",
                    cfg.colorClass,
                  )}
                >
                  {cfg.label}
                </span>
                {ts && (
                  <span className="ml-auto text-text-faint font-mono text-[10px]">{ts}</span>
                )}
              </div>

              {/* Body */}
              <p className="text-[12px] text-text-secondary leading-relaxed whitespace-pre-wrap">
                {msg.body}
              </p>
            </div>
          );
        })}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}
