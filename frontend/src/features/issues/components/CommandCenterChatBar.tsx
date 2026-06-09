"use client";

import { useState } from "react";
import { Loader2, Send } from "lucide-react";

import { Button } from "@/components/ui/button";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { sendConductorMessage } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { useI18n } from "@/providers/I18nProvider";

interface Props {
  issueId: string;
  disabled?: boolean;
  clarifyQuestion?: string | null;
  onSent?: () => void;
}

export function CommandCenterChatBar({ issueId, disabled, clarifyQuestion, onSent }: Props) {
  const { addToast } = useToast();
  const { t } = useI18n();
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);

  const submit = async () => {
    const text = draft.trim();
    if (!text || disabled || sending) return;
    setSending(true);
    try {
      await sendConductorMessage(issueId, clarifyQuestion ? `[CLARIFY] ${text}` : text);
      setDraft("");
      onSent?.();
      addToast({ type: "success", title: t("issue.command.chatSent") });
    } catch (err) {
      addToast({ type: "error", title: t("issue.command.chatFailed"), message: err instanceof Error ? err.message : String(err) });
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="sticky bottom-0 z-30 border-t border-border-subtle bg-background/95 px-3 py-2 backdrop-blur sm:px-5">
      {clarifyQuestion && !disabled && (
        <div
          data-density="conductor-clarification-banner"
          className="motion-essential relative mx-auto mb-2 flex max-w-[1640px] items-start gap-2 overflow-hidden rounded-lg border border-status-awaiting/35 bg-status-awaiting/10 px-3 py-2 text-xs text-status-awaiting"
        >
          <span
            aria-hidden
            className="pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-status-awaiting/70 to-transparent"
          />
          <AgentThinkingIndicator phase="thinking" size={12} className="mt-0.5 shrink-0" />
          <p className="min-w-0 flex-1">
            {t("issue.command.clarifyBanner", { question: clarifyQuestion })}
          </p>
        </div>
      )}
      <div className="mx-auto flex max-w-[1640px] items-end gap-2 rounded-lg border border-border-subtle bg-surface-raised p-1.5">
        <textarea
          value={draft}
          disabled={disabled || sending}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void submit();
            }
          }}
          rows={2}
          placeholder={disabled ? t("issue.command.chatPausedPlaceholder") : clarifyQuestion ? t("issue.command.chatAnswerPlaceholder") : t("issue.command.chatPlaceholder")}
          className="min-h-9 flex-1 resize-none rounded-md border border-transparent bg-transparent px-2.5 py-1.5 text-sm outline-none placeholder:text-text-muted focus:border-brand/40"
        />
        <Button onClick={() => void submit()} disabled={disabled || sending || !draft.trim()} className="gap-2 rounded-md bg-brand text-black hover:bg-brand-strong">
          {sending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
          {t("issue.command.send")}
        </Button>
      </div>
    </div>
  );
}
