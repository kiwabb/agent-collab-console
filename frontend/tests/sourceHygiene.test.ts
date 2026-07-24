import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const SRC_ROOT = join(process.cwd(), "src");
const TEST_ROOT = join(process.cwd(), "tests");
const API_ROOT = join(SRC_ROOT, "lib/api");
const REPO_ROOT = join(process.cwd(), "..");

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

function collectFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const fullPath = join(dir, entry);
    const stat = statSync(fullPath);
    if (stat.isDirectory()) {
      out.push(...collectFiles(fullPath));
      continue;
    }
    out.push(fullPath);
  }
  return out;
}

function rel(file: string): string {
  return relative(SRC_ROOT, file);
}

function relTest(file: string): string {
  return relative(TEST_ROOT, file);
}

function relApi(file: string): string {
  return relative(API_ROOT, file);
}

type PackageJson = {
  scripts?: Record<string, string>;
  dependencies?: Record<string, string>;
  devDependencies?: Record<string, string>;
};

function readPackageJson(): PackageJson {
  return JSON.parse(readFileSync(join(process.cwd(), "package.json"), "utf-8")) as PackageJson;
}

function dependencyVersion(packageJson: PackageJson, name: string): string | undefined {
  return packageJson.dependencies?.[name] ?? packageJson.devDependencies?.[name];
}

function dependencyMajor(packageJson: PackageJson, name: string): string | undefined {
  return dependencyVersion(packageJson, name)?.match(/^[^\d]*(\d+)\./)?.[1];
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
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

test("runtime source narrows object payloads with guards instead of broad assertions", () => {
  const broadAssertionPatterns = [
    /\bas\s+Record<string,\s*unknown>/,
    /\bas\s+\{\s*data\?:\s*unknown\s*\}/,
    /\bas\s+\{\s*detail\?:\s*unknown\s*\}/,
    /\bas\s+\{\s*hidden\?:\s*boolean\s*\}/,
    /\bas\s+\{\s*type\?:\s*string\s*\}/,
    /\bas\s+\{\s*id\?:\s*string;\s*created_at\?:\s*string\s*\|\s*null\s*\}\[]/,
  ];
  const problems: string[] = [];

  for (const file of collectSourceFiles(SRC_ROOT)) {
    const source = readFileSync(file, "utf-8");
    for (const pattern of broadAssertionPatterns) {
      if (pattern.test(source)) {
        problems.push(`${rel(file)} uses broad object assertion ${pattern}`);
      }
    }
  }

  assert.deepEqual(problems, []);
});

test("frontend tests avoid explicit any fixtures", () => {
  const problems: string[] = [];
  for (const file of collectSourceFiles(TEST_ROOT)) {
    if (file.endsWith("sourceHygiene.test.ts")) continue;
    const source = readFileSync(file, "utf-8");
    if (/:\s*any\b|\bas\s+any\b/.test(source)) {
      problems.push(`${relTest(file)} uses explicit any`);
    }
  }
  assert.deepEqual(problems, []);
});

test("frontend API tests parse request bodies through fetch test helpers", () => {
  const requestBodyJsonParse =
    /JSON\.parse\s*\(\s*(?:String\([^)]*\.init\?\.body\)|[^)]*\.init\?\.body\s+as\s+string)/;
  const problems: string[] = [];

  for (const file of collectSourceFiles(TEST_ROOT)) {
    if (file.endsWith("sourceHygiene.test.ts")) continue;
    const source = readFileSync(file, "utf-8");
    if (requestBodyJsonParse.test(source)) {
      problems.push(`${relTest(file)} parses fetch request body JSON directly`);
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

test("frontend source and tests stay on TypeScript files", () => {
  const problems = [...collectFiles(SRC_ROOT), ...collectFiles(TEST_ROOT)]
    .filter((file) => /\.(?:js|jsx)$/.test(file))
    .map((file) => relative(process.cwd(), file));

  assert.deepEqual(problems, []);
});

test("runtime source does not ship ad hoc debug output", () => {
  const problems: string[] = [];
  for (const file of collectSourceFiles(SRC_ROOT)) {
    const source = readFileSync(file, "utf-8");
    if (/\bconsole\.(?:log|debug|warn)\s*\(/.test(source)) {
      problems.push(`${rel(file)} uses console log/debug/warn`);
    }
    if (/\bdebugger\b/.test(source)) {
      problems.push(`${rel(file)} contains debugger`);
    }
  }

  assert.deepEqual(problems, []);
});

test("runtime JSON parsing goes through shared helpers", () => {
  const allowed = new Set(["app/layout.tsx", "lib/utils.tsx"]);
  const problems: string[] = [];

  for (const file of collectSourceFiles(SRC_ROOT)) {
    const relativeFile = rel(file);
    if (allowed.has(relativeFile)) continue;
    const source = readFileSync(file, "utf-8");
    if (/JSON\.parse\s*\(/.test(source)) {
      problems.push(`${relativeFile} parses JSON directly`);
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

test("split API modules route ordinary JSON requests through shared helpers", () => {
  const allowedRawFetchLines = new Map<string, Set<string>>([
    [
      "fetch.ts",
      new Set([
        "return fetch(url, init);",
        "const p = fetch(url, init);",
        "const response = await fetch(url, init);",
        ": await fetch(url, options.init);",
      ]),
    ],
    [
      "health.ts",
      new Set([
        "const response = await fetch(`${API_BASE}/health`);",
        "const response = await fetch(`${API_BASE}/codex/status`);",
      ]),
    ],
    ["issues.ts", new Set(["const response = await fetch(`${url}&format=${format}`);"])],
    ["tasks.ts", new Set(["const response = await fetch(`${url}&format=${format}`);"])],
    [
      "skills.ts",
      new Set([
        'const response = await fetch(url.toString(), { method: "DELETE" });',
        "const response = await fetch(`${API_BASE}/skills/proxy?url=${encodeURIComponent(url)}`);",
      ]),
    ],
  ]);
  const problems: string[] = [];

  for (const file of collectSourceFiles(API_ROOT)) {
    const apiFile = relApi(file);
    const allowedLines = allowedRawFetchLines.get(apiFile) ?? new Set<string>();
    const source = readFileSync(file, "utf-8");
    for (const line of source.split("\n")) {
      const trimmed = line.trim();
      if (/\bfetch\s*\(/.test(trimmed) && !allowedLines.has(trimmed)) {
        problems.push(`${apiFile} has unlisted raw fetch: ${trimmed}`);
      }
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

test("execution process stream hooks parse frames through typed helpers", () => {
  const problems: string[] = [];
  const hookFiles = [
    join(SRC_ROOT, "hooks", "useExecutionProcesses.ts"),
    join(SRC_ROOT, "hooks", "useExecutionProcessLogStream.ts"),
    join(SRC_ROOT, "hooks", "useExecutionProcessMessageStream.ts"),
  ];
  for (const file of hookFiles) {
    const source = readFileSync(file, "utf-8");
    if (/JSON\.parse\s*\(/.test(source)) {
      problems.push(`${rel(file)} parses JSON directly instead of executionProcessStreamFrames`);
    }
  }

  assert.deepEqual(problems, []);
});

test("project conductor loop dock does not subscribe to an unsupported event stream", () => {
  const source = readFileSync(
    join(SRC_ROOT, "features/projects/components/ProjectConductorThreadDock.tsx"),
    "utf-8",
  );

  assert.doesNotMatch(source, /JSON\.parse\s*\(/);
  assert.doesNotMatch(source, /EventSource|conductor\/stream/);
  assert.match(source, /startProjectConductorLoop/);
});

test("codex log normalizer parses runtime log JSON through shared helpers", () => {
  const source = readFileSync(join(SRC_ROOT, "lib", "codexLogNormalizer.ts"), "utf-8");

  assert.doesNotMatch(source, /JSON\.parse\s*\(/);
  assert.doesNotMatch(
    source,
    /\bas\s+(?:string|number|boolean|string\s+\|\s+null|string\s+\|\s+undefined|unknown\[])/,
  );
  assert.match(source, /safeJsonRecord/);
  assert.match(source, /stringValue/);
});

test("issue result surfaces parse JSON through feature helpers", () => {
  const files = [
    "features/issues/components/AgentDecisionDrawer.tsx",
    "features/issues/components/IssueNarrativeTimeline.tsx",
    "features/issues/hooks/useDecisionTimeline.ts",
    "features/issues/tabs/TasksRunsTab.tsx",
    "features/runs/AgentLiveTimeline.tsx",
  ];
  const problems: string[] = [];

  for (const file of files) {
    const source = readFileSync(join(SRC_ROOT, file), "utf-8");
    if (/JSON\.parse\s*\(/.test(source)) {
      problems.push(`${file} parses issue result JSON directly`);
    }
  }

  assert.deepEqual(problems, []);
});

test("runtime payload surfaces narrow primitives before reading fields", () => {
  const files = [
    "features/audit/AuditLogPage.tsx",
    "features/benchmarks/BenchmarksPage.tsx",
    "features/issues/hooks/useDecisionTimeline.ts",
    "features/runs/toolBlocks/ToolBlocks.tsx",
  ];
  const primitiveAssertionPattern =
    /\bas\s+(?:string|number|boolean|string\s+\|\s+null|string\s+\|\s+undefined|unknown\[])/;
  const problems: string[] = [];

  for (const file of files) {
    const source = readFileSync(join(SRC_ROOT, file), "utf-8");
    if (primitiveAssertionPattern.test(source)) {
      problems.push(`${file} uses primitive assertions at a runtime payload boundary`);
    }
  }

  assert.deepEqual(problems, []);
});

test("CLI and build tools stay out of production dependencies", () => {
  const packageJson = readPackageJson();
  const devOnlyPackages = [
    "@next/swc-wasm-nodejs",
    "@tailwindcss/postcss",
    "@typescript-eslint/eslint-plugin",
    "@typescript-eslint/parser",
    "eslint",
    "eslint-config-next",
    "prettier",
    "shadcn",
    "tailwindcss",
    "tsx",
    "typescript",
  ];
  const problems: string[] = [];

  for (const packageName of devOnlyPackages) {
    if (packageJson.dependencies?.[packageName] !== undefined) {
      problems.push(`${packageName} is listed in production dependencies`);
    }
    if (packageJson.devDependencies?.[packageName] === undefined) {
      problems.push(`${packageName} is missing from devDependencies`);
    }

    const importPattern = new RegExp(
      `from ["']${escapeRegExp(packageName)}(?:/[^"']*)?["']|import\\(["']${escapeRegExp(packageName)}(?:/[^"']*)?["']\\)`,
    );
    for (const file of collectSourceFiles(SRC_ROOT)) {
      const source = readFileSync(file, "utf-8");
      if (importPattern.test(source)) {
        problems.push(`${rel(file)} imports dev-only package ${packageName}`);
      }
    }
  }

  assert.deepEqual(problems, []);
});

test("frontend stack docs match package versions", () => {
  const packageJson = readPackageJson();
  assert.equal(dependencyMajor(packageJson, "next"), "15");
  assert.equal(dependencyMajor(packageJson, "tailwindcss"), "4");
  assert.equal(dependencyMajor(packageJson, "@base-ui/react"), "1");

  const stackSpecFiles = [
    ".trellis/spec/ccgui/frontend/index.md",
    ".trellis/spec/ccgui/frontend/component-guidelines.md",
    ".trellis/spec/ccgui/frontend/directory-structure.md",
    ".trellis/spec/vibe-kanban/frontend/index.md",
    ".trellis/spec/vibe-kanban/frontend/component-guidelines.md",
    ".trellis/spec/vibe-kanban/frontend/directory-structure.md",
  ];
  const problems: string[] = [];

  for (const specFile of stackSpecFiles) {
    const source = readFileSync(join(REPO_ROOT, specFile), "utf-8");
    if (!source.includes("Next.js 15")) {
      problems.push(`${specFile} does not document Next.js 15`);
    }
    if (!source.includes("Tailwind v4")) {
      problems.push(`${specFile} does not document Tailwind v4`);
    }
    if (!source.includes("@base-ui/react")) {
      problems.push(`${specFile} does not document @base-ui/react`);
    }
    if (/Next\.js 14|Next 14/.test(source)) {
      problems.push(`${specFile} still documents Next.js 14`);
    }
    if (/Tailwind v3|Tailwind CSS v3/.test(source)) {
      problems.push(`${specFile} still documents Tailwind v3`);
    }
  }

  assert.deepEqual(problems, []);
});

test("frontend format scripts cover runtime and test TypeScript files", () => {
  const packageJson = readPackageJson();
  const format = packageJson.scripts?.["format"];
  const formatCheck = packageJson.scripts?.["format:check"];

  assert.equal(
    format,
    "prettier --write 'src/**/*.{ts,tsx}' 'tests/**/*.{ts,tsx}' 'scripts/**/*.{ts,mjs}'",
  );
  assert.equal(
    formatCheck,
    "prettier --check 'src/**/*.{ts,tsx}' 'tests/**/*.{ts,tsx}' 'scripts/**/*.{ts,mjs}'",
  );
});

test("prerendered issue grid storage helpers guard browser storage access", () => {
  const issueGrid = readFileSync(join(SRC_ROOT, "features/issues/IssueGrid.tsx"), "utf-8");

  assert.match(issueGrid, /typeof window === "undefined"\) return \[\]/);
  assert.match(issueGrid, /window\.localStorage\.getItem\(RECENT_SEARCHES_KEY\)/);
  assert.match(issueGrid, /window\.localStorage\.setItem\(RECENT_SEARCHES_KEY/);
  assert.match(issueGrid, /safeJsonStringArray\(stored\)/);
});

test("task execution QA report status parsing is centralized", () => {
  const taskExecutionSheet = readFileSync(
    join(SRC_ROOT, "features/workbench/components/TaskExecutionSheet.tsx"),
    "utf-8",
  );
  const helper = readFileSync(join(SRC_ROOT, "features/workbench/qaReportStatus.ts"), "utf-8");

  assert.doesNotMatch(taskExecutionSheet, /JSON\.parse\s*\(/);
  assert.match(taskExecutionSheet, /readQaReportStatus/);
  assert.match(helper, /safeJsonRecord/);
});
