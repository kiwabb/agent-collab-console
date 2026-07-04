import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const SRC_ROOT = join(process.cwd(), "src");

function collectSourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const fullPath = join(dir, entry);
    const stat = statSync(fullPath);
    if (stat.isDirectory()) {
      out.push(...collectSourceFiles(fullPath));
      continue;
    }
    if (/\.(ts|tsx)$/.test(entry)) out.push(fullPath);
  }
  return out;
}

function rel(file: string): string {
  return relative(SRC_ROOT, file);
}

test("runtime source avoids broad TypeScript escape hatches", () => {
  const problems: string[] = [];
  for (const file of collectSourceFiles(SRC_ROOT)) {
    const source = readFileSync(file, "utf-8");
    if (/:\s*any\b|\bas\s+any\b/.test(source)) {
      problems.push(`${rel(file)} uses explicit any`);
    }
    if (/\bas\s+unknown\s+as\b/.test(source)) {
      problems.push(`${rel(file)} uses a double assertion through unknown`);
    }
    if (/@ts-ignore|@ts-expect-error/.test(source)) {
      problems.push(`${rel(file)} suppresses TypeScript errors`);
    }
    if (/import\(["']@\/lib\/types["']\)/.test(source)) {
      problems.push(`${rel(file)} uses inline '@/lib/types' imports instead of import type`);
    }
  }
  assert.deepEqual(problems, []);
});

test("runtime source uses static imports instead of CommonJS require", () => {
  const problems: string[] = [];
  for (const file of collectSourceFiles(SRC_ROOT)) {
    const source = readFileSync(file, "utf-8");
    if (/\brequire\(/.test(source)) {
      problems.push(`${rel(file)} uses require(...)`);
    }
  }
  assert.deepEqual(problems, []);
});

test("runtime source imports split API modules instead of the monolithic barrel", () => {
  const problems: string[] = [];
  for (const file of collectSourceFiles(SRC_ROOT)) {
    if (file.endsWith(join("src", "lib", "api.ts"))) continue;
    const source = readFileSync(file, "utf-8");
    if (/from ["']@\/lib\/api["']|import\(["']@\/lib\/api["']\)/.test(source)) {
      problems.push(`${rel(file)} imports the monolithic API barrel`);
    }
  }
  assert.deepEqual(problems, []);
});

test("runtime source uses static split API imports", () => {
  const problems: string[] = [];
  for (const file of collectSourceFiles(SRC_ROOT)) {
    if (file.includes(join("src", "lib", "api"))) continue;
    const source = readFileSync(file, "utf-8");
    if (/import\(["']@\/lib\/api\/[^"']+["']\)/.test(source)) {
      problems.push(`${rel(file)} dynamically imports a split API module`);
    }
  }
  assert.deepEqual(problems, []);
});

test("runtime source has no generated placeholder copy", () => {
  const problems: string[] = [];
  for (const file of collectSourceFiles(SRC_ROOT)) {
    const source = readFileSync(file, "utf-8");
    if (/待补充|Generate Startup Scripts/.test(source)) {
      problems.push(`${rel(file)} contains generated placeholder copy`);
    }
  }
  assert.deepEqual(problems, []);
});
