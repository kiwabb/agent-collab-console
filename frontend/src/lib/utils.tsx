import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function safeJsonParse(input: string): unknown | null {
  try {
    return JSON.parse(input) as unknown;
  } catch {
    return null;
  }
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function safeJsonRecord(input: string): Record<string, unknown> | null {
  const parsed = safeJsonParse(input);
  return isRecord(parsed) ? parsed : null;
}

export function safeJsonStringArray(input: string): string[] | null {
  const parsed = safeJsonParse(input);
  return Array.isArray(parsed) && parsed.every((item) => typeof item === "string") ? parsed : null;
}

export function safeJsonNumberRecord(input: string): Record<string, number> | null {
  const parsed = safeJsonRecord(input);
  if (!parsed) return null;
  const out: Record<string, number> = {};
  for (const [key, value] of Object.entries(parsed)) {
    if (typeof value === "number" && Number.isFinite(value)) {
      out[key] = value;
    }
  }
  return out;
}

// Parse @mentions and #123 issue refs from message content
export function parseMessageContent(content: string): {
  text: string;
  mentions: string[];
  issueRefs: string[];
} {
  const mentions: string[] = [];
  const issueRefs: string[] = [];

  // Match @username patterns
  const mentionRegex = /@(\w+)/g;
  let match: RegExpExecArray | null;
  while ((match = mentionRegex.exec(content)) !== null) {
    const mention = match[1];
    if (mention) mentions.push(mention);
  }

  // Match #123 issue reference patterns (numbers only)
  const issueRefRegex = /#(\d+)/g;
  while ((match = issueRefRegex.exec(content)) !== null) {
    const issueRef = match[1];
    if (issueRef) issueRefs.push(issueRef);
  }

  return { text: content, mentions, issueRefs };
}

// Render message content with @mention and #123 highlighting as React nodes
export function renderMessageWithLinks(content: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let key = 0;

  // Combined regex for @mentions and #123 refs
  const regex = /@(\w+)|#(\d+)/g;
  let match;

  while ((match = regex.exec(content)) !== null) {
    // Add text before the match
    if (match.index > lastIndex) {
      parts.push(content.slice(lastIndex, match.index));
    }

    if (match[1] !== undefined) {
      // @mention
      parts.push(
        <span key={key++} className="text-brand font-bold">
          @{match[1]}
        </span>,
      );
    } else if (match[2] !== undefined) {
      // #123 issue ref
      parts.push(
        <span key={key++} className="text-warning font-bold">
          #{match[2]}
        </span>,
      );
    }

    lastIndex = match.index + match[0].length;
  }

  // Add remaining text
  if (lastIndex < content.length) {
    parts.push(content.slice(lastIndex));
  }

  return parts.length > 0 ? parts : [content];
}
