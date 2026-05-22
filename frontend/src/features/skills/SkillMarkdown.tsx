"use client";

import { memo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import rehypeHighlight from "rehype-highlight";
import "highlight.js/styles/github-dark.css";
import { cn } from "@/lib/utils";

// Skill content is user-curated (user explicitly added the link) so passing
// `rehype-raw` is acceptable — README files on GitHub commonly use raw HTML
// (<details>, <summary>, <img>, <picture>, ...) that ReactMarkdown otherwise
// escapes. Do NOT reuse this renderer for agent-generated content.

const components: Components = {
  p: ({ node, ...props }) => (
    <p {...props} className="my-2 leading-relaxed text-[13.5px] text-foreground/90" />
  ),
  ul: ({ node, ...props }) => (
    <ul {...props} className="my-2 pl-5 list-disc space-y-1 text-[13.5px] text-foreground/90" />
  ),
  ol: ({ node, ...props }) => (
    <ol {...props} className="my-2 pl-5 list-decimal space-y-1 text-[13.5px] text-foreground/90" />
  ),
  li: ({ node, ...props }) => <li {...props} className="leading-relaxed" />,
  h1: ({ node, ...props }) => (
    <h1 {...props} className="mt-4 mb-2 text-lg font-black tracking-tight" />
  ),
  h2: ({ node, ...props }) => (
    <h2 {...props} className="mt-4 mb-2 text-[15px] font-black tracking-tight" />
  ),
  h3: ({ node, ...props }) => (
    <h3 {...props} className="mt-3 mb-2 text-[14px] font-bold tracking-tight" />
  ),
  h4: ({ node, ...props }) => (
    <h4 {...props} className="mt-2 mb-1 text-[13px] font-bold tracking-tight" />
  ),
  hr: () => <hr className="my-4 border-border-subtle" />,
  blockquote: ({ node, ...props }) => (
    <blockquote
      {...props}
      className="my-2 pl-3 border-l-2 border-brand/40 text-text-secondary italic"
    />
  ),
  a: ({ node, ...props }) => (
    <a
      {...props}
      target="_blank"
      rel="noreferrer noopener"
      className="text-brand underline-offset-2 hover:underline"
    />
  ),
  img: ({ node, ...props }) => (
    // Skill markdown can reference arbitrary local/remote images outside the Next Image allowlist.
    // eslint-disable-next-line @next/next/no-img-element
    <img {...props} className="my-2 max-w-full rounded-md border border-border-subtle" alt={props.alt ?? ""} />
  ),
  table: ({ node, ...props }) => (
    <div className="my-2 overflow-auto rounded-lg border border-border-subtle">
      <table {...props} className="w-full text-[12px] text-text-secondary" />
    </div>
  ),
  thead: ({ node, ...props }) => <thead {...props} className="bg-surface-raised/60" />,
  th: ({ node, ...props }) => (
    <th {...props} className="px-3 py-1.5 text-left font-bold uppercase tracking-widest text-[10px]" />
  ),
  td: ({ node, ...props }) => (
    <td {...props} className="px-3 py-1.5 border-t border-border-subtle align-top" />
  ),
  code: ({ node, className, children, ...props }) => {
    const isInline = !(className && /language-/.test(className));
    if (isInline) {
      return (
        <code
          {...props}
          className="px-1 py-0.5 rounded bg-surface-raised border border-border-subtle font-mono text-[12px]"
        >
          {children}
        </code>
      );
    }
    return (
      <code className={cn(className, "font-mono text-[12px] leading-relaxed")} {...props}>
        {children}
      </code>
    );
  },
  pre: ({ node, ...props }) => (
    <pre
      {...props}
      className="my-2 px-3 py-2 overflow-auto rounded-lg bg-background/70 border border-border-subtle"
    />
  ),
  details: ({ node, ...props }) => (
    <details {...props} className="my-2 rounded-md border border-border-subtle bg-surface-raised/40 px-3 py-2 [&[open]>summary]:mb-2" />
  ),
  summary: ({ node, ...props }) => (
    <summary {...props} className="cursor-pointer select-none text-[13px] font-semibold marker:text-text-muted" />
  ),
};

interface Props {
  content: string;
  className?: string;
}

export const SkillMarkdown = memo(function SkillMarkdown({ content, className }: Props) {
  return (
    <div className={cn("max-w-none break-words", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw, rehypeHighlight]}
        components={components}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
});
