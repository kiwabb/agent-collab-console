"use client";

import { useState } from "react";
import { Send, Loader2 } from "lucide-react";
import { appendConductorMessage } from "@/lib/api";

interface Props {
  projectId: string | null;
  onSent?: () => void;
}

export function ConductorChatBar({ projectId, onSent }: Props) {
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    const text = message.trim();
    if (!text || !projectId || loading) return;
    setLoading(true);
    try {
      await appendConductorMessage(projectId, text);
      setMessage("");
      onSent?.();
    } catch {
      // silent — caller can surface errors if needed
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
    <div className="flex items-center gap-2 border-t border-border-subtle bg-surface px-3 py-2">
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
          <Loader2 size={14} className="animate-spin" />
        ) : (
          <Send size={14} />
        )}
      </button>
    </div>
  );
}
