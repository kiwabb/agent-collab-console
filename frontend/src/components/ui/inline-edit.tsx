"use client";

import { useState, useRef, useEffect } from "react";
import { Pencil, Check, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface InlineEditProps {
  value: string;
  onSave: (value: string) => void;
  placeholder?: string;
  className?: string;
  textClassName?: string;
  multiline?: boolean;
  disabled?: boolean;
}

export function InlineEdit({
  value,
  onSave,
  placeholder = "Click to edit...",
  className,
  textClassName,
  multiline = false,
  disabled = false,
}: InlineEditProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(value);
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null);

  useEffect(() => {
    setEditValue(value);
  }, [value]);

  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [isEditing]);

  const handleSave = () => {
    const trimmed = editValue.trim();
    if (trimmed !== value) {
      onSave(trimmed);
    }
    setIsEditing(false);
  };

  const handleCancel = () => {
    setEditValue(value);
    setIsEditing(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSave();
    } else if (e.key === "Escape") {
      handleCancel();
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
          className="p-1.5 rounded-lg bg-success/10 text-success hover:bg-success/20 transition-colors"
          title="Save"
        >
          <Check size={14} />
        </button>
        <button
          onClick={handleCancel}
          className="p-1.5 rounded-lg bg-error/10 text-error hover:bg-error/20 transition-colors"
          title="Cancel"
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
        className
      )}
      onClick={() => !disabled && setIsEditing(true)}
    >
      <span
        className={cn(
          "text-sm font-medium text-foreground/80 hover:text-foreground transition-colors",
          !value && "text-text-muted italic",
          textClassName
        )}
      >
        {value || placeholder}
      </span>
      {!disabled && (
        <div className="opacity-0 group-hover:opacity-100 transition-opacity">
          <Pencil size={12} className="text-text-muted" />
        </div>
      )}
    </div>
  );
}
