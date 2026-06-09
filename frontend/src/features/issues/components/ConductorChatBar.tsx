"use client";

import { useState } from "react";
import { Send } from "lucide-react";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { appendConductorMessage } from "@/lib/api";

interface Props {
  projectId: string | null;
  onSent?: () => void;
}

export function ConductorChatBar({ projectId, onSent }: Props) {
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async () => {
    const text = message.trim();
    if (!text || !projectId || loading) return;
    setLoading(true);
    setError(null);
    try {
      await appendConductorMessage(projectId, text);
      setMessage("");
      onSent?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send message");
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSubmit();
    }
  };

  const disabled = !projectId || loading;

  return (
    <div className="border-t border-border-subtle bg-surface px-3 py-2">
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          placeholder={
            projectId ? "Send a message to Conductor…" : "No project linked."
          }
          className="flex-1 rounded-md border border-border-subtle bg-background px-3 py-1.5 text-[13px] text-foreground placeholder:text-text-muted outline-none focus:ring-2 focus:ring-brand/40 disabled:opacity-50 disabled:cursor-not-allowed"
        />
        <button
          type="button"
          onClick={() => void handleSubmit()}
          disabled={disabled || !message.trim()}
          className="shrink-0 inline-flex items-center justify-center gap-1.5 rounded-md bg-brand hover:bg-brand-strong text-black font-semibold text-[13px] px-3 py-1.5 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? (
            <AgentThinkingIndicator phase="thinking" size={14} />
          ) : (
            <Send size={14} />
          )}
        </button>
      </div>
      {error && <p className="mt-1.5 text-[11px] text-error">{error}</p>}
    </div>
  );
}
