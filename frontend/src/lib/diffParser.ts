export type DiffLineType = "add" | "del" | "context" | "hunk" | "meta";

export type DiffLine = {
  type: DiffLineType;
  oldLine: number | null;
  newLine: number | null;
  text: string;
};

export type DiffFile = {
  header: string;
  oldPath: string | null;
  newPath: string | null;
  isNew: boolean;
  isDeleted: boolean;
  isBinary: boolean;
  additions: number;
  deletions: number;
  lines: DiffLine[];
  rawPatch: string;
};

const HUNK_RE = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/;

function parseLinesIntoHunks(chunk: string[]): DiffLine[] {
  const result: DiffLine[] = [];
  let oldLine = 0;
  let newLine = 0;
  let inHunk = false;

  for (const line of chunk) {
    if (line.startsWith("@@")) {
      const m = HUNK_RE.exec(line);
      if (m) {
        oldLine = Number(m[1]);
        newLine = Number(m[2]);
      }
      result.push({ type: "hunk", oldLine: null, newLine: null, text: line });
      inHunk = true;
      continue;
    }
    if (!inHunk) continue;

    if (line.startsWith("+")) {
      result.push({ type: "add", oldLine: null, newLine, text: line.slice(1) });
      newLine += 1;
    } else if (line.startsWith("-")) {
      result.push({ type: "del", oldLine, newLine: null, text: line.slice(1) });
      oldLine += 1;
    } else if (line.startsWith(" ")) {
      result.push({ type: "context", oldLine, newLine, text: line.slice(1) });
      oldLine += 1;
      newLine += 1;
    } else if (line.startsWith("\\")) {
      result.push({ type: "meta", oldLine: null, newLine: null, text: line });
    }
  }
  return result;
}

export function parseUnifiedDiff(text: string): DiffFile[] {
  if (!text || !text.trim()) return [];

  const rawLines = text.split("\n");
  const files: DiffFile[] = [];

  // Split into per-file blocks at "diff --git" boundaries.
  const blockStarts: number[] = [];
  for (let i = 0; i < rawLines.length; i++) {
    if (rawLines[i].startsWith("diff --git ")) blockStarts.push(i);
  }

  for (let b = 0; b < blockStarts.length; b++) {
    const start = blockStarts[b];
    const end = b + 1 < blockStarts.length ? blockStarts[b + 1] : rawLines.length;
    const block = rawLines.slice(start, end);
    const rawPatch = block.join("\n");

    const headerLine = block[0];
    // Extract paths from "diff --git a/<p> b/<q>"
    const gitMatch = /^diff --git a\/(.+) b\/(.+)$/.exec(headerLine);
    let oldPath: string | null = gitMatch ? gitMatch[1] : null;
    let newPath: string | null = gitMatch ? gitMatch[2] : null;

    let isNew = false;
    let isDeleted = false;
    let isBinary = false;

    // Walk meta-lines before first @@
    for (const line of block.slice(1)) {
      if (line.startsWith("@@")) break;
      if (line.startsWith("new file mode")) { isNew = true; oldPath = null; }
      else if (line.startsWith("deleted file mode")) { isDeleted = true; newPath = null; }
      else if (/^Binary files/.test(line)) { isBinary = true; }
      else if (line.startsWith("--- /dev/null")) { isNew = true; oldPath = null; }
      else if (line.startsWith("+++ /dev/null")) { isDeleted = true; newPath = null; }
      else if (line.startsWith("--- a/")) { oldPath = line.slice(6); }
      else if (line.startsWith("+++ b/")) { newPath = line.slice(6); }
    }

    const lines = parseLinesIntoHunks(block);

    let additions = 0;
    let deletions = 0;
    for (const l of lines) {
      if (l.type === "add") additions++;
      else if (l.type === "del") deletions++;
    }

    files.push({
      header: headerLine,
      oldPath,
      newPath,
      isNew,
      isDeleted,
      isBinary,
      additions,
      deletions,
      lines,
      rawPatch,
    });
  }

  return files;
}

export function displayPath(file: DiffFile): string {
  return file.newPath ?? file.oldPath ?? "unknown";
}
