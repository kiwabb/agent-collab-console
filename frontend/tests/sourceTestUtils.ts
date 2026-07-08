import { readFileSync } from "node:fs";
import { join } from "node:path";

const SRC_ROOT = join(process.cwd(), "src");

export function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

export function compactSource(source: string): string {
  return source
    .replace(/\s+/g, " ")
    .replace(/\{\s+/g, "{")
    .replace(/\s+\}/g, "}")
    .replace(/\bimport \{([^}]+)\} from/g, (_match, names: string) => {
      return `import { ${names.trim()} } from`;
    })
    .replace(/\bimport type \{([^}]+)\} from/g, (_match, names: string) => {
      return `import type { ${names.trim()} } from`;
    })
    .trim();
}

export function readCompactSource(relativePath: string): string {
  return compactSource(readSource(relativePath));
}
