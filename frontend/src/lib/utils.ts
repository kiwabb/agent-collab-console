import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// Parse @mentions and #123 issue refs from message content
export function parseMessageContent(content: string): { text: string; mentions: string[]; issueRefs: string[] } {
  const mentions: string[] = [];
  const issueRefs: string[] = [];

  // Match @username patterns
  const mentionRegex = /@(\w+)/g;
  let match;
  while ((match = mentionRegex.exec(content)) !== null) {
    mentions.push(match[1]);
  }

  // Match #123 issue reference patterns (numbers only)
  const issueRefRegex = /#(\d+)/g;
  while ((match = issueRefRegex.exec(content)) !== null) {
    issueRefs.push(match[1]);
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
        <span key={key++} className="text-brand font-bold">@{match[1]}</span>
      );
    } else if (match[2] !== undefined) {
      // #123 issue ref
      parts.push(
        <span key={key++} className="text-warning font-bold">#{match[2]}</span>
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
