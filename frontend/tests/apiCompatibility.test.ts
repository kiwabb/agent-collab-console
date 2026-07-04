import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const SRC_ROOT = join(process.cwd(), "src");
const API_SOURCE = readFileSync(join(SRC_ROOT, "lib/api.ts"), "utf-8");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

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

function splitApiExportNames(moduleName: string): Set<string> | null {
  if (moduleName.includes("/")) return null;
  const sourcePath = join(SRC_ROOT, "lib/api", `${moduleName}.ts`);
  try {
    const source = readFileSync(sourcePath, "utf-8");
    const names = new Set<string>();
    for (const match of source.matchAll(/export\s+(?:async\s+)?function\s+(\w+)/g)) {
      if (match[1]) names.add(match[1]);
    }
    for (const match of source.matchAll(/export\s+(?:const|let|var)\s+(\w+)/g)) {
      if (match[1]) names.add(match[1]);
    }
    for (const match of source.matchAll(/export\s+(?:interface|type)\s+(\w+)/g)) {
      if (match[1]) names.add(match[1]);
    }
    for (const match of source.matchAll(/export\s+(?:type\s+)?\{([^}]+)\}/g)) {
      for (const part of (match[1] ?? "").split(",")) {
        const raw = part.trim();
        if (!raw) continue;
        const alias = raw.split(/\s+as\s+/);
        const exportedName = alias[1] ?? alias[0] ?? "";
        if (exportedName) names.add(exportedName.trim());
      }
    }
    return names;
  } catch {
    return null;
  }
}

test("monolithic api entrypoint keeps split-module compatibility exports", () => {
  assert.match(
    API_SOURCE,
    /getEmbeddingStatus,[\s\S]*} from "\.\/api\/knowledge";/,
    "AppStatusBar and legacy callers need getEmbeddingStatus from '@/lib/api'",
  );
  assert.match(
    API_SOURCE,
    /getTeamNotes,[\s\S]*} from "\.\/api\/knowledge";/,
    "legacy callers need team notes helpers from '@/lib/api'",
  );
  assert.match(
    API_SOURCE,
    /export function getGlobalEventsStreamUrl/,
    "useExecutionProcesses needs getGlobalEventsStreamUrl from '@/lib/api'",
  );
});

test("runtime-critical callers import split api modules directly", () => {
  assert.match(
    readSource("hooks/useExecutionProcesses.ts"),
    /from "@\/lib\/api\/health"/,
    "global websocket URL builder should come from api/health, not the monolithic barrel",
  );
  assert.match(
    readSource("hooks/useExecutionProcesses.ts"),
    /from "@\/lib\/api\/tasks"/,
    "execution process snapshots should come from api/tasks, not the monolithic barrel",
  );
  assert.match(
    readSource("hooks/useExecutionProcesses.ts"),
    /from "@\/lib\/api\/workspaces"/,
    "workspace stream URL builder should come from api/workspaces, not the monolithic barrel",
  );
  assert.match(
    readSource("hooks/useBackendStatus.ts"),
    /from "@\/lib\/api\/health"/,
    "backend health polling should come from api/health",
  );
  assert.match(
    readSource("hooks/useExecutionProcessLogStream.ts"),
    /from "@\/lib\/api\/tasks"/,
    "process log stream URL should come from api/tasks",
  );
  assert.match(
    readSource("hooks/useExecutionProcessMessageStream.ts"),
    /from "@\/lib\/api\/tasks"/,
    "process message stream URL should come from api/tasks",
  );
  assert.match(
    readSource("features/knowledge/KnowledgePage.tsx"),
    /from "@\/lib\/api\/knowledge"/,
    "knowledge page embedding/search/reindex calls should come from api/knowledge",
  );
  assert.match(
    readSource("features/knowledge/TeamNotesEditor.tsx"),
    /from "@\/lib\/api\/knowledge"/,
    "team notes editor helpers should come from api/knowledge",
  );
  assert.match(
    readSource("features/issues/components/SimilarIssuesCard.tsx"),
    /from "@\/lib\/api\/knowledge"/,
    "similar issue lookup should come from api/knowledge",
  );
  assert.match(
    readSource("features/issues/components/useIssueBudget.ts"),
    /from "@\/lib\/api\/stats"/,
    "issue budget polling should come from api/stats",
  );
  assert.match(
    readSource("features/issues/components/IssueSideStack.tsx"),
    /from "@\/lib\/api\/stats"/,
    "issue side stack cost and policy calls should come from api/stats",
  );
  assert.match(
    readSource("features/issues/components/TasksOverviewBar.tsx"),
    /from "@\/lib\/api\/stats"/,
    "tasks overview cost stats calls should come from api/stats",
  );
  assert.match(
    readSource("features/issues/components/TasksOverviewBar.tsx"),
    /from "@\/lib\/api\/tasks"/,
    "tasks overview task list should come from api/tasks",
  );
  assert.match(
    readSource("features/issues/components/IssueNarrativeTimeline.tsx"),
    /from "@\/lib\/api\/tasks"/,
    "issue narrative timeline task list should come from api/tasks",
  );
  assert.match(
    readSource("features/issues/components/AgentDecisionDrawer.tsx"),
    /from "@\/lib\/api\/tasks"/,
    "agent decision drawer task lookup should come from api/tasks",
  );
  assert.match(
    readSource("features/issues/components/DispatchDrawer.tsx"),
    /from "@\/lib\/api\/tasks"/,
    "dispatch drawer task rerun/terminate calls should come from api/tasks",
  );
  assert.match(
    readSource("features/workbench/components/AccountPopover.tsx"),
    /from "@\/lib\/api\/stats"/,
    "account popover cost stats calls should come from api/stats",
  );
  assert.match(
    readSource("features/workbench/components/AccountPopover.tsx"),
    /from "@\/lib\/api\/health"/,
    "account popover health check should come from api/health",
  );
  assert.match(
    readSource("features/inbox/InboxDashboard.tsx"),
    /from "@\/lib\/api\/workspaces"/,
    "inbox workspace summary should come from api/workspaces",
  );
  assert.match(
    readSource("features/audit/AuditLogPage.tsx"),
    /from "@\/lib\/api\/audit"/,
    "audit log page should import audit API from api/audit",
  );
  assert.match(
    readSource("features/audit/AuditRoleChainView.tsx"),
    /from "@\/lib\/api\/audit"/,
    "audit role chain view should import audit types from api/audit",
  );
  assert.match(
    readSource("features/audit/auditRoleChains.ts"),
    /from "@\/lib\/api\/audit"/,
    "audit role chain helpers should import audit types from api/audit",
  );
  assert.match(
    readSource("features/skills/SkillsLibraryPage.tsx"),
    /from "@\/lib\/api\/skills"/,
    "skills library API calls should come from api/skills",
  );
  assert.match(
    readSource("features/agents/AgentLibraryPage.tsx"),
    /from "@\/lib\/api\/agents"/,
    "agent library API calls should come from api/agents",
  );
  assert.match(
    readSource("features/workflow/AgentCatalogPanel.tsx"),
    /from "@\/lib\/api\/agents"/,
    "agent catalog panel should import listAgents from api/agents",
  );
  assert.match(
    readSource("features/approvals/ApprovalsPage.tsx"),
    /from "@\/lib\/api\/approvals"/,
    "approvals page should import approval helpers from api/approvals",
  );
  assert.match(
    readSource("features/approvals/ApprovalsPage.tsx"),
    /from "@\/lib\/api\/tasks"/,
    "approvals page task list should come from api/tasks",
  );
  assert.match(
    readSource("features/workbench/WorkbenchPage.tsx"),
    /from "@\/lib\/api\/approvals"/,
    "workbench approval helpers should come from api/approvals",
  );
  assert.match(
    readSource("features/workbench/WorkbenchPage.tsx"),
    /from "@\/lib\/api\/issues"/,
    "workbench issue calls and legacy phase transitions should come from api/issues",
  );
  assert.match(
    readSource("features/workbench/WorkbenchPage.tsx"),
    /from "@\/lib\/api\/tasks"/,
    "workbench task actions and execution process calls should come from api/tasks",
  );
  assert.match(
    readSource("store/workbenchStore.ts"),
    /from '@\/lib\/api\/approvals'/,
    "workbench store pending approvals should come from api/approvals",
  );
  assert.match(
    readSource("store/workbenchStore.ts"),
    /from '@\/lib\/api\/tasks'/,
    "workbench store task list and help requests should come from api/tasks",
  );
  assert.match(
    readSource("app/benchmarks/page.tsx"),
    /from "@\/lib\/api\/benchmarks"/,
    "benchmarks route page should import benchmark helpers from api/benchmarks",
  );
  assert.match(
    readSource("features/benchmarks/BenchmarksPage.tsx"),
    /from "@\/lib\/api\/benchmarks"/,
    "benchmarks feature page should import benchmark helpers from api/benchmarks",
  );
  assert.match(
    readSource("features/resume/ResumePage.tsx"),
    /from "@\/lib\/api\/resume"/,
    "resume page API calls should come from api/resume",
  );
  assert.match(
    readSource("features/resume/ResumeSidebar.tsx"),
    /from "@\/lib\/api\/resume"/,
    "resume sidebar types should come from api/resume",
  );
  assert.match(
    readSource("features/prototype/ProjectPrototypesPage.tsx"),
    /from "@\/lib\/api\/prototypes"/,
    "project prototypes page API calls should come from api/prototypes",
  );
  assert.match(
    readSource("features/prototype/ProjectPrototypesRoutePage.tsx"),
    /from "@\/lib\/api\/projects"/,
    "project prototypes route should import project lookup from api/projects",
  );
  const prototypeCanvasSource = readSource("features/prototype/PrototypeCanvas.tsx");
  assert.match(
    prototypeCanvasSource,
    /from "@\/lib\/api\/prototypes"/,
    "prototype canvas API calls should come from api/prototypes",
  );
  assert.doesNotMatch(
    prototypeCanvasSource,
    /import\("@\/lib\/api"\)/,
    "prototype canvas should not dynamically import the monolithic API barrel",
  );
  assert.match(
    readSource("features/conductors/ConductorMonitorPage.tsx"),
    /from "@\/lib\/api\/projects"/,
    "conductor monitor project-conductor calls should come from api/projects",
  );
  assert.match(
    readSource("features/projects/ProjectConductorPage.tsx"),
    /from "@\/lib\/api\/projects"/,
    "project conductor page calls should come from api/projects",
  );
  assert.match(
    readSource("features/projects/ProjectWorkspacesPage.tsx"),
    /from "@\/lib\/api\/projects"/,
    "project workspaces page project/run calls should come from api/projects",
  );
  assert.match(
    readSource("features/projects/ProjectWorkspacesPage.tsx"),
    /from "@\/lib\/api\/workspaces"/,
    "project workspaces page workspace calls should come from api/workspaces",
  );
  assert.match(
    readSource("features/projects/ProjectsPage.tsx"),
    /from "@\/lib\/api\/projects"/,
    "projects page project management calls should come from api/projects",
  );
  assert.match(
    readSource("features/projects/ProjectsPage.tsx"),
    /startProjectScriptTask,[\s\S]*} from "@\/lib\/api\/projects"/,
    "projects page operations engineer script task should come from api/projects",
  );
  assert.match(
    readSource("features/projects/ProjectsPage.tsx"),
    /from "@\/lib\/api\/tasks"/,
    "projects page script task polling should come from api/tasks",
  );
  assert.match(
    readSource("features/projects/ProjectDashboard.tsx"),
    /from "@\/lib\/api\/projects"/,
    "project dashboard project stats calls should come from api/projects",
  );
  assert.match(
    readSource("features/projects/ProjectDashboard.tsx"),
    /from "@\/lib\/api\/workspaces"/,
    "project dashboard workspace calls should come from api/workspaces",
  );
  assert.match(
    readSource("features/projects/CreateProjectDialog.tsx"),
    /from "@\/lib\/api\/projects"/,
    "create project dialog calls should come from api/projects",
  );
  assert.match(
    readSource("features/resume/useResumeProjects.ts"),
    /from "@\/lib\/api\/projects"/,
    "resume project list hook should import listProjects from api/projects",
  );
  assert.match(
    readSource("features/workbench/components/AppSidebar.tsx"),
    /from "@\/lib\/api\/projects"/,
    "app sidebar project list should come from api/projects",
  );
  assert.match(
    readSource("features/workbench/components/AppSidebar.tsx"),
    /from "@\/lib\/api\/workspaces"/,
    "app sidebar workspace list should come from api/workspaces",
  );
  assert.match(
    readSource("features/workbench/components/AppSidebar.tsx"),
    /from "@\/lib\/api\/issues"/,
    "app sidebar issue list should come from api/issues",
  );
  assert.match(
    readSource("features/workbench/components/AppHeader.tsx"),
    /from "@\/lib\/api\/projects"/,
    "app header project list should come from api/projects",
  );
  assert.match(
    readSource("features/workbench/components/CommandPalette.tsx"),
    /from "@\/lib\/api\/projects"/,
    "command palette project list should come from api/projects",
  );
  assert.match(
    readSource("features/issues/IssueGrid.tsx"),
    /from "@\/lib\/api\/projects"/,
    "issue grid branch lookup should come from api/projects",
  );
  assert.match(
    readSource("hooks/useBrowserNotifications.ts"),
    /from "@\/lib\/api\/issues"/,
    "browser notifications issue lookup should come from api/issues",
  );
  assert.match(
    readSource("features/artifacts/ArtifactsHubPage.tsx"),
    /from "@\/lib\/api\/issues"/,
    "artifacts hub issue/artifact calls should come from api/issues",
  );
  assert.match(
    readSource("features/issues/tabs/ArtifactsTab.tsx"),
    /from "@\/lib\/api\/issues"/,
    "issue artifacts tab should import artifacts from api/issues",
  );
  assert.match(
    readSource("features/issues/components/GitInfoCard.tsx"),
    /from "@\/lib\/api\/issues"/,
    "git info card merge/diff calls should come from api/issues",
  );
  assert.match(
    readSource("features/workbench/components/CommandPalette.tsx"),
    /from "@\/lib\/api\/workspaces"/,
    "command palette workspace list should come from api/workspaces",
  );
  assert.match(
    readSource("features/workbench/components/CommandPalette.tsx"),
    /from "@\/lib\/api\/issues"/,
    "command palette issue search should come from api/issues",
  );
  assert.match(
    readSource("features/projects/components/ProjectConductorThreadDock.tsx"),
    /from "@\/lib\/api\/projects"/,
    "project conductor loop should come from api/projects",
  );
  assert.match(
    readSource("features/projects/components/ProjectConductorThreadDock.tsx"),
    /from "@\/lib\/api\/fetch"/,
    "project conductor stream URL base should come from api/fetch",
  );
  assert.match(
    readSource("features/issues/tabs/CollabFeedTab.tsx"),
    /from "@\/lib\/api\/conductors"/,
    "collab feed agent messages should come from api/conductors",
  );
  assert.match(
    readSource("features/issues/tabs/DagTab.tsx"),
    /from "@\/lib\/api\/tasks"/,
    "DAG retry dispatch should import runCodexTask from api/tasks",
  );
  assert.match(
    readSource("features/agents/dock/useAgentStatus.ts"),
    /from "@\/lib\/api\/tasks"/,
    "agent dock task and execution process polling should come from api/tasks",
  );
  assert.match(
    readSource("features/agents/dock/useAgentStatus.ts"),
    /from "@\/lib\/api\/conductors"/,
    "agent dock graph polling should come from api/conductors",
  );
  assert.match(
    readSource("features/issues/components/CommandCenterChatBar.tsx"),
    /from "@\/lib\/api\/conductors"/,
    "command center conductor messages should come from api/conductors",
  );
  assert.match(
    readSource("features/issues/components/TimelineThinkingTurns.tsx"),
    /from "@\/lib\/api\/conductors"/,
    "timeline conductor turn type should come from api/conductors",
  );
  assert.match(
    readSource("features/issues/components/ConductorChatBar.tsx"),
    /from "@\/lib\/api\/conductors"/,
    "project conductor chat messages should come from api/conductors",
  );
  assert.match(
    readSource("features/settings/SettingsPage.tsx"),
    /from "@\/lib\/api\/runtime"/,
    "settings runtime catalog calls should come from api/runtime",
  );
  assert.match(
    readSource("features/workspaces/WorkspaceConsole.tsx"),
    /from "@\/lib\/api\/runtime"/,
    "workspace console runtime catalog calls should come from api/runtime",
  );
  assert.match(
    readSource("features/workspaces/WorkspaceConsole.tsx"),
    /from "@\/lib\/api\/workspaces"/,
    "workspace console workspace lookup should come from api/workspaces",
  );
  assert.match(
    readSource("features/workspaces/WorkspaceConsole.tsx"),
    /from "@\/lib\/api\/tasks"/,
    "workspace console task list should come from api/tasks",
  );
  assert.match(
    readSource("features/workspaces/WorkspaceBoard.tsx"),
    /from "@\/lib\/api\/runtime"/,
    "workspace board runtime catalog calls should come from api/runtime",
  );
  assert.match(
    readSource("features/workspaces/WorkspaceBoard.tsx"),
    /from "@\/lib\/api\/workspaces"/,
    "workspace board workspace lookup should come from api/workspaces",
  );
  assert.match(
    readSource("features/issues/tabs/TasksRunsTab.tsx"),
    /from "@\/lib\/api\/runtime"/,
    "tasks/runs tab runtime catalog calls should come from api/runtime",
  );
  assert.match(
    readSource("features/issues/tabs/TasksRunsTab.tsx"),
    /from "@\/lib\/api\/tasks"/,
    "tasks/runs tab task actions and execution process calls should come from api/tasks",
  );
  assert.match(
    readSource("features/issues/tabs/DiffMergeTab.tsx"),
    /from "@\/lib\/api\/tasks"/,
    "diff/merge tab task list should come from api/tasks",
  );
  assert.match(
    readSource("features/issues/IssueDetailPage.tsx"),
    /from "@\/lib\/api\/tasks"/,
    "issue detail core refresh should load tasks from api/tasks",
  );
  assert.match(
    readSource("features/workbench/components/TaskExecutionSheet.tsx"),
    /from "@\/lib\/api\/tasks"/,
    "task execution sheet task actions should come from api/tasks",
  );
  assert.match(
    readSource("store/workbenchStore.ts"),
    /from '@\/lib\/api\/runtime'/,
    "workbench store runtime catalog calls should come from api/runtime",
  );
  assert.match(
    readSource("store/workbenchStore.ts"),
    /from '@\/lib\/api\/workspaces'/,
    "workbench store workspace list should come from api/workspaces",
  );
});

test("runtime source does not import the monolithic api barrel directly", () => {
  for (const file of collectSourceFiles(SRC_ROOT)) {
    if (file.endsWith(join("src", "lib", "api.ts"))) continue;
    const source = readFileSync(file, "utf-8");
    assert.doesNotMatch(
      source,
      /from ["']@\/lib\/api["']|import\(["']@\/lib\/api["']\)/,
      `${file} should import a split api module instead of '@/lib/api'`,
    );
  }
});

test("runtime split api imports reference exported names", () => {
  const problems: string[] = [];
  for (const file of collectSourceFiles(SRC_ROOT)) {
    if (file.includes(join("src", "lib", "api"))) continue;
    const source = readFileSync(file, "utf-8");
    const imports = source.matchAll(
      /import\s+(?:type\s+)?\{([^{}]+)\}\s+from\s+["']@\/lib\/api\/([^"']+)["']/g,
    );
    for (const match of imports) {
      const moduleName = match[2] ?? "";
      const exportNames = splitApiExportNames(moduleName);
      if (!exportNames) {
        problems.push(`${file}: missing split api module ${moduleName}`);
        continue;
      }
      for (const part of (match[1] ?? "").split(",")) {
        const raw = part.trim();
        if (!raw) continue;
        const imported = raw.replace(/^type\s+/, "").split(/\s+as\s+/)[0]?.trim() ?? "";
        if (!exportNames.has(imported)) {
          problems.push(`${file}: ${imported} is not exported by @/lib/api/${moduleName}`);
        }
      }
    }
    const dynamicImports = source.matchAll(
      /const\s+\{([^{}]+)\}\s*=\s*await\s+import\(["']@\/lib\/api\/([^"']+)["']\)/g,
    );
    for (const match of dynamicImports) {
      const moduleName = match[2] ?? "";
      const exportNames = splitApiExportNames(moduleName);
      if (!exportNames) {
        problems.push(`${file}: missing split api module ${moduleName}`);
        continue;
      }
      for (const part of (match[1] ?? "").split(",")) {
        const raw = part.trim();
        if (!raw) continue;
        const imported = raw.split(":")[0]?.trim() ?? "";
        if (!exportNames.has(imported)) {
          problems.push(`${file}: ${imported} is not exported by @/lib/api/${moduleName}`);
        }
      }
    }
  }
  assert.deepEqual(problems, []);
});
