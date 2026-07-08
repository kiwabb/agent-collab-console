"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { Pencil, Check, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { useI18n } from "@/providers/I18nProvider";

interface InlineEditProps {
  value: string;
  onSave: (value: string) => Promise<void> | void;
  placeholder?: string;
  className?: string;
  textClassName?: string;
  multiline?: boolean;
  disabled?: boolean;
  autoSave?: boolean;
}

export function InlineEdit({
  value,
  onSave,
  placeholder = "Click to edit...",
  className,
  textClassName,
  multiline = false,
  disabled = false,
  autoSave = true,
}: InlineEditProps) {
  const { t } = useI18n();
  const resolvedPlaceholder =
    placeholder === "Click to edit..." ? t("ui.clickToEdit") : placeholder;
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(value);
  const [isSaving, setIsSaving] = useState(false);
  const [showSaved, setShowSaved] = useState(false);
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null);
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setEditValue(value);
  }, [value]);

  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [isEditing]);

  const handleSave = useCallback(async () => {
    const trimmed = editValue.trim();
    if (trimmed === value) {
      setIsEditing(false);
      return;
    }
    setIsSaving(true);
    try {
      await onSave(trimmed);
      setIsEditing(false);
      if (autoSave) {
        setShowSaved(true);
        setTimeout(() => setShowSaved(false), 1500);
      }
    } finally {
      setIsSaving(false);
    }
  }, [editValue, value, onSave, autoSave]);

  const scheduleAutoSave = useCallback(() => {
    if (!autoSave || !isEditing) return;
    if (saveTimeoutRef.current) {
      clearTimeout(saveTimeoutRef.current);
    }
    saveTimeoutRef.current = setTimeout(() => {
      handleSave();
    }, 1000);
  }, [autoSave, isEditing, handleSave]);

  useEffect(() => {
    return () => {
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current);
      }
    };
  }, []);

  const handleCancel = () => {
    setEditValue(value);
    setIsEditing(false);
    if (saveTimeoutRef.current) {
      clearTimeout(saveTimeoutRef.current);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSave();
    } else if (e.key === "Escape") {
      handleCancel();
    } else if (autoSave) {
      scheduleAutoSave();
    }
  };

  if (isEditing) {
    return (
      <div className={cn("flex items-center gap-2", className)}>
        {multiline ? (
          <textarea
            ref={inputRef as React.RefObject<HTMLTextAreaElement>}
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onKeyDown={handleKeyDown}
            className="flex-1 px-3 py-2 text-sm rounded-lg bg-surface-input border border-brand/50 outline-none resize-none focus:ring-2 focus:ring-brand/20"
            rows={3}
          />
        ) : (
          <input
            ref={inputRef as React.RefObject<HTMLInputElement>}
            type="text"
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onKeyDown={handleKeyDown}
            className="flex-1 px-3 py-1.5 text-sm rounded-lg bg-surface-input border border-brand/50 outline-none focus:ring-2 focus:ring-brand/20"
          />
        )}
        <button
          onClick={handleSave}
          disabled={isSaving}
          data-density={isSaving ? "inline-edit-save-tool" : "inline-edit-save"}
          className={cn(
            "p-1.5 rounded-lg bg-success/10 text-success hover:bg-success/20 transition-colors disabled:opacity-50",
            isSaving && "motion-essential",
          )}
          title={t("ui.saveShortcut")}
          aria-label={t("ui.save")}
        >
          {isSaving ? <AgentThinkingIndicator phase="tool" size={14} /> : <Check size={14} />}
        </button>
        <button
          onClick={handleCancel}
          disabled={isSaving}
          className="p-1.5 rounded-lg bg-error/10 text-error hover:bg-error/20 transition-colors disabled:opacity-50"
          title={t("ui.cancelShortcut")}
          aria-label={t("ui.cancel")}
        >
          <X size={14} />
        </button>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "group relative flex items-center gap-2",
        !disabled && "cursor-pointer",
        className,
      )}
      onClick={() => !disabled && setIsEditing(true)}
    >
      <span
        className={cn(
          "text-sm font-medium text-foreground/80 hover:text-foreground transition-colors",
          !value && "text-text-muted italic",
          textClassName,
        )}
      >
        {value || resolvedPlaceholder}
      </span>
      {!disabled && (
        <div className="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1">
          {showSaved && (
            <span className="text-[9px] font-black text-success uppercase tracking-widest animate-in fade-in duration-200">
              {t("ui.saved")}
            </span>
          )}
          <Pencil size={12} className="text-text-muted" />
        </div>
      )}
    </div>
  );
}
