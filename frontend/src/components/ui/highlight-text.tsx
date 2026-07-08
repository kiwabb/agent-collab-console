"use client";

import { cn } from "@/lib/utils";

interface HighlightTextProps {
  text: string;
  query: string;
  className?: string;
  highlightClassName?: string;
}

export function HighlightText({
  text,
  query,
  className,
  highlightClassName = "bg-warning/40 text-foreground rounded px-0.5",
}: HighlightTextProps) {
  if (!query.trim()) {
    return <span className={className}>{text}</span>;
  }

  const regex = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi");
  const parts = text.split(regex);

  return (
    <span className={className}>
      {parts.map((part, i) =>
        regex.test(part) ? (
          <mark key={i} className={cn("not-italic", highlightClassName)}>
            {part}
          </mark>
        ) : (
          part
        ),
      )}
    </span>
  );
}
