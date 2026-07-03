export interface ResumeStats {
  characters: number;
  words: number;
  lines: number;
  sizeBytes: number;
}

export function deriveResumeStats(markdown: string): ResumeStats {
  const trimmed = markdown.trim();
  return {
    characters: markdown.length,
    words: trimmed ? trimmed.split(/\s+/).filter(Boolean).length : 0,
    lines: markdown ? markdown.split(/\r\n|\r|\n/).length : 0,
    sizeBytes: new TextEncoder().encode(markdown).length,
  };
}

export function formatByteCount(bytes: number): string {
  if (bytes < 1024) return `${bytes.toLocaleString()} B`;
  const kib = bytes / 1024;
  if (kib < 1024) return `${kib.toFixed(kib >= 10 ? 0 : 1)} KB`;
  const mib = kib / 1024;
  return `${mib.toFixed(mib >= 10 ? 0 : 1)} MB`;
}
