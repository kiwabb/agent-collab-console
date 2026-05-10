"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { Pencil, Check, X, Loader2, Eye, Edit3, Bold, Italic, Code, Link } from "lucide-react";
import { cn } from "@/lib/utils";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import "highlight.js/styles/github-dark.css";

interface MarkdownEditorProps {
  value: string;
  onSave: (value: string) => Promise<void> | void;
  placeholder?: string;
  className?: string;
  textClassName?: string;
  multiline?: boolean;
  disabled?: boolean;
  autoSave?: boolean;
}

export function MarkdownEditor({
  value,
  onSave,
  placeholder = "Click to edit...",
  className,
  textClassName,
  multiline = false,
  disabled = false,
  autoSave = true,
}: MarkdownEditorProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(value);
  const [isSaving, setIsSaving] = useState(false);
  const [showSaved, setShowSaved] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setEditValue(value);
  }, [value]);

  useEffect(() => {
    if (isEditing && inputRef.current && !showPreview) {
      inputRef.current.focus();
    }
  }, [isEditing, showPreview]);

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
    setShowPreview(false);
    if (saveTimeoutRef.current) {
      clearTimeout(saveTimeoutRef.current);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey && !e.ctrlKey) {
      e.preventDefault();
      handleSave();
    } else if (e.key === "Escape") {
      handleCancel();
    } else if (autoSave) {
      scheduleAutoSave();
    }
    if (e.ctrlKey || e.metaKey) {
      if (e.key === "b") {
        e.preventDefault();
        insertMarkdown("**", "**");
      } else if (e.key === "i") {
        e.preventDefault();
        insertMarkdown("*", "*");
      } else if (e.key === "e") {
        e.preventDefault();
        insertMarkdown("`", "`");
      }
    }
  };

  const insertMarkdown = (before: string, after: string = "") => {
    const textarea = inputRef.current;
    if (!textarea) return;
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const selectedText = editValue.substring(start, end);
    const newText = editValue.substring(0, start) + before + selectedText + after + editValue.substring(end);
    setEditValue(newText);
    setTimeout(() => {
      textarea.focus();
      textarea.setSelectionRange(start + before.length, end + before.length);
    }, 0);
  };

  if (isEditing) {
    return (
      <div className={cn("flex flex-col gap-2", className)}>
        {multiline && (
          <div className="flex items-center gap-1 border border-border-subtle rounded-lg bg-surface-raised p-1.5">
            <button
              type="button"
              onClick={() => insertMarkdown("**", "**")}
              className="p-1.5 rounded hover:bg-surface-hover transition-colors"
              title="Bold (Ctrl+B)"
            >
              <Bold size={14} className="text-text-muted" />
            </button>
            <button
              type="button"
              onClick={() => insertMarkdown("*", "*")}
              className="p-1.5 rounded hover:bg-surface-hover transition-colors"
              title="Italic (Ctrl+I)"
            >
              <Italic size={14} className="text-text-muted" />
            </button>
            <button
              type="button"
              onClick={() => insertMarkdown("`", "`")}
              className="p-1.5 rounded hover:bg-surface-hover transition-colors"
              title="Inline Code (Ctrl+E)"
            >
              <Code size={14} className="text-text-muted" />
            </button>
            <button
              type="button"
              onClick={() => insertMarkdown("[", "](url)")}
              className="p-1.5 rounded hover:bg-surface-hover transition-colors"
              title="Link"
            >
              <Link size={14} className="text-text-muted" />
            </button>
            <div className="w-px h-4 bg-border-subtle mx-1" />
            <button
              type="button"
              onClick={() => setShowPreview(p => !p)}
              className={cn("p-1.5 rounded hover:bg-surface-hover transition-colors", showPreview && "bg-surface-hover")}
              title="Preview"
            >
              {showPreview ? <Edit3 size={14} className="text-brand" /> : <Eye size={14} className="text-text-muted" />}
            </button>
          </div>
        )}
        {showPreview ? (
          <div className="p-4 rounded-lg bg-surface-input border border-brand/50 min-h-[100px] prose prose-sm dark:prose-invert max-w-none [&_pre]:bg-background [&_code]:bg-background [&_code]:px-1 [&_code]:rounded">
            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>{editValue}</ReactMarkdown>
          </div>
        ) : (
          <textarea
            ref={inputRef}
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onKeyDown={handleKeyDown}
            className="flex-1 px-3 py-2 text-sm rounded-lg bg-surface-input border border-brand/50 outline-none resize-none focus:ring-2 focus:ring-brand/20 font-mono"
            rows={multiline ? 6 : undefined}
            placeholder={placeholder}
          />
        )}
        <div className="flex items-center gap-2">
          <button
            onClick={handleSave}
            disabled={isSaving}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-success/10 text-success hover:bg-success/20 transition-colors disabled:opacity-50 text-xs font-bold"
            title="Save (Enter)"
          >
            {isSaving ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
            Save
          </button>
          <button
            onClick={handleCancel}
            disabled={isSaving}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-error/10 text-error hover:bg-error/20 transition-colors disabled:opacity-50 text-xs font-bold"
            title="Cancel (Esc)"
          >
            <X size={12} />
            Cancel
          </button>
          {showSaved && (
            <span className="text-[9px] font-black text-success uppercase tracking-widest animate-in fade-in duration-200">Saved</span>
          )}
        </div>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "group relative flex items-center gap-2",
        !disabled && "cursor-pointer",
        className
      )}
      onClick={() => !disabled && setIsEditing(true)}
    >
      {value ? (
        <div className={cn(
          "text-sm leading-relaxed prose prose-sm dark:prose-invert max-w-none [&_pre]:bg-background [&_code]:bg-background/80 [&_code]:px-1 [&_code]:rounded",
          textClassName
        )}>
          <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>{value}</ReactMarkdown>
        </div>
      ) : (
        <span className={cn("italic text-text-muted", textClassName)}>{placeholder}</span>
      )}
      {!disabled && (
        <div className="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1">
          {showSaved && (
            <span className="text-[9px] font-black text-success uppercase tracking-widest animate-in fade-in duration-200">Saved</span>
          )}
          <Pencil size={12} className="text-text-muted" />
        </div>
      )}
    </div>
  );
}