import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';

type WorkbenchTransitionFlag =
  | 'isTransitioningToArchitecture'
  | 'isTransitioningToDevelopment'
  | 'isTransitioningToTesting';
type WorkbenchStoreShape = WorkbenchState & WorkbenchActions;
type WorkbenchSetter = (updater: (state: WorkbenchStoreShape) => void) => void;

// Conductor-driven restart: the old "transition to architecture/development/testing"
// buttons map onto a single action — kick the Conductor loop on the issue.
// Conductor decides which agent to dispatch next; the phase label on the issue
// updates as nodes complete.
async function startGraphForIssue(
  get: () => WorkbenchStoreShape,
  set: WorkbenchSetter,
  flagKey: WorkbenchTransitionFlag,
  issueId: string,
  newPhase: string,
) {
  set((state) => { state[flagKey] = true; });
  try {
    await autoStartIssueGraph(issueId);
    const issue = get().issues.find((i) => i.id === issueId);
    if (issue && get().updateIssue) {
      get().updateIssue(issueId, { ...issue, current_phase: newPhase });
    }
    if (get().loadIssueArtifacts) {
      await get().loadIssueArtifacts(issueId);
    }
  } catch (err) {
    set((state) => { state.error = err instanceof Error ? err.message : 'Conductor start failed'; });
    throw err;
  } finally {
    set((state) => { state[flagKey] = false; });
  }
}
import type {
  Workspace,
  Project,
  CodexIssue,
  CodexTask,
  ExecutionProcess,
  Artifact,
  HelpRequest,
  Approval,
  LogEvent,
  CodexTaskMessage,
  RuntimeCatalog,
  RunMode,
  SendMessageResult,
} from '@/lib/types';
import type { BusEvent } from '@/contexts/ExecutionProcessesContext';
import { autoStartIssueGraph } from '@/lib/api/conductors';
import { getCodexIssues, getCodexIssueArtifacts } from '@/lib/api/issues';
import { getPendingApprovals } from '@/lib/api/approvals';
import { listProjects, getProject } from '@/lib/api/projects';
import { getRuntimeCatalog } from '@/lib/api/runtime';
import { chatCodexTask, getCodexTasks, getTaskHelpRequests, refineCodexTask, sendCodexTask } from '@/lib/api/tasks';
import { getWorkspaces } from '@/lib/api/workspaces';

type NavigationState = 'home' | 'workspace' | 'issue';

interface WorkbenchState {
  // Navigation
  view: NavigationState;
  currentWorkspaceId: string | null;
  currentIssueId: string | null;
  currentTaskId: string | null;

  // Core data
  projects: Project[];
  currentProject: Project | null;
  workspaces: Workspace[];
  issues: CodexIssue[];
  tasks: CodexTask[];
  artifacts: Artifact[];
  executionProcesses: Record<string, ExecutionProcess>;
  helpRequests: HelpRequest[];
  pendingApprovals: Approval[];

  // Runtime
  runtimeCatalog: RuntimeCatalog | null;

  // UI state
  selectedProcessId: string | null;
  optimisticProcess: ExecutionProcess | null;
  processLogs: LogEvent[];
  processMessages: CodexTaskMessage[];
  lastResolvedMode: 'chat' | 'refine' | null;

  // Loading states
  isLoadingWorkspaces: boolean;
  isLoadingIssues: boolean;
  isLoadingLogs: boolean;
  isLoadingMessages: boolean;
  isLoadingProcess: boolean;

  // Connection state
  isConnected: boolean;
  wasConnected: boolean;
  connectionWarning: string | null;
  error: string | null;
  lastEvent: BusEvent | null;

  // Transitioning states
  isTransitioningToArchitecture: boolean;
  isTransitioningToDevelopment: boolean;
  isTransitioningToTesting: boolean;
  isRunning: boolean;
}

interface WorkbenchActions {
  // Navigation
  setView: (view: NavigationState) => void;
  setCurrentWorkspaceId: (id: string | null) => void;
  setCurrentIssueId: (id: string | null) => void;
  setCurrentTaskId: (id: string | null) => void;

  // Project
  setCurrentProject: (project: Project | null) => void;
  setProjects: (projects: Project[]) => void;

  // Workspace
  setWorkspaces: (workspaces: Workspace[]) => void;
  updateWorkspaces: (updater: (workspaces: Workspace[]) => Workspace[]) => void;
  addWorkspace: (workspace: Workspace) => void;
  removeWorkspace: (id: string) => void;

  // Issues
  setIssues: (issues: CodexIssue[]) => void;
  updateIssues: (updater: (issues: CodexIssue[]) => CodexIssue[]) => void;
  addIssue: (issue: CodexIssue) => void;
  updateIssue: (id: string, updates: Partial<CodexIssue>) => void;
  removeIssue: (id: string) => void;

  // Tasks
  setTasks: (tasks: CodexTask[]) => void;
  updateTasks: (updater: (tasks: CodexTask[]) => CodexTask[]) => void;
  addTask: (task: CodexTask) => void;
  updateTask: (id: string, updates: Partial<CodexTask>) => void;
  removeTask: (id: string) => void;

  // Artifacts
  setArtifacts: (artifacts: Artifact[]) => void;

  // Execution Processes
  setExecutionProcesses: (processes: Record<string, ExecutionProcess>) => void;
  updateExecutionProcess: (id: string, updates: Partial<ExecutionProcess>) => void;
  addExecutionProcess: (process: ExecutionProcess) => void;
  setSelectedProcessId: (id: string | null) => void;
  setOptimisticProcess: (process: ExecutionProcess | null) => void;
  clearOptimisticProcess: () => void;

  // Logs & Messages
  setProcessLogs: (logs: LogEvent[]) => void;
  setProcessMessages: (messages: CodexTaskMessage[]) => void;
  appendProcessMessage: (message: CodexTaskMessage) => void;
  appendProcessLog: (log: LogEvent) => void;

  // Help Requests
  setHelpRequests: (requests: HelpRequest[]) => void;

  // Approvals
  setPendingApprovals: (approvals: Approval[]) => void;
  updatePendingApprovals: (updater: (approvals: Approval[]) => Approval[]) => void;
  removeApproval: (id: string) => void;

  // Runtime Catalog
  setRuntimeCatalog: (catalog: RuntimeCatalog | null) => void;

  // Loading states
  setIsLoadingWorkspaces: (loading: boolean) => void;
  setIsLoadingIssues: (loading: boolean) => void;
  setIsLoadingLogs: (loading: boolean) => void;
  setIsLoadingMessages: (loading: boolean) => void;
  setIsLoadingProcess: (loading: boolean) => void;

  // Connection
  setIsConnected: (connected: boolean) => void;
  setWasConnected: (wasConnected: boolean) => void;
  setConnectionWarning: (warning: string | null) => void;

  // Error
  setError: (error: string | null) => void;

  // Transitions
  setIsTransitioningToArchitecture: (transitioning: boolean) => void;
  setIsTransitioningToDevelopment: (transitioning: boolean) => void;
  setIsTransitioningToTesting: (transitioning: boolean) => void;
  setIsRunning: (running: boolean) => void;

  // Last event (from WebSocket)
  setLastEvent: (event: BusEvent | null) => void;

  // Async actions
  loadProjects: () => Promise<void>;
  loadProject: (id: string) => Promise<void>;
  loadWorkspaces: (projectId: string) => Promise<void>;
  loadWorkspaceData: (workspaceId: string) => Promise<void>;
  loadIssueArtifacts: (issueId: string) => Promise<void>;
  loadPendingApprovals: () => Promise<void>;
  loadRuntimeCatalog: () => Promise<void>;
  
  // High-level Actions
  transitionToArchitecture: (issueId: string) => Promise<void>;
  transitionToDevelopment: (issueId: string) => Promise<void>;
  transitionToTesting: (issueId: string) => Promise<void>;
  sendMessage: (taskId: string, content: string, mode: RunMode) => Promise<void>;

  // Reset
  resetWorkspaceState: () => void;
  reset: () => void;
}

const initialState: WorkbenchState = {
  view: 'home',
  currentWorkspaceId: null,
  currentIssueId: null,
  currentTaskId: null,
  projects: [],
  currentProject: null,
  workspaces: [],
  issues: [],
  tasks: [],
  artifacts: [],
  executionProcesses: {},
  helpRequests: [],
  pendingApprovals: [],
  runtimeCatalog: null,
  selectedProcessId: null,
  optimisticProcess: null,
  processLogs: [],
  processMessages: [],
  lastResolvedMode: null,
  isLoadingWorkspaces: false,
  isLoadingIssues: false,
  isLoadingLogs: false,
  isLoadingMessages: false,
  isLoadingProcess: false,
  isConnected: false,
  wasConnected: false,
  connectionWarning: null,
  error: null,
  lastEvent: null,
  isTransitioningToArchitecture: false,
  isTransitioningToDevelopment: false,
  isTransitioningToTesting: false,
  isRunning: false,
};

export const useWorkbenchStore = create<WorkbenchState & WorkbenchActions>()(
  immer((set, get) => ({
    ...initialState,

    // Navigation
    setView: (view) => set((state) => { state.view = view; }),
    setCurrentWorkspaceId: (id) => set((state) => { state.currentWorkspaceId = id; }),
    setCurrentIssueId: (id) => set((state) => { state.currentIssueId = id; }),
    setCurrentTaskId: (id) => set((state) => { state.currentTaskId = id; }),

    // Project
    setCurrentProject: (project) => set((state) => { state.currentProject = project; }),
    setProjects: (projects) => set((state) => { state.projects = projects; }),

    // Workspace
    setWorkspaces: (workspaces) => set((state) => { state.workspaces = workspaces; }),
    updateWorkspaces: (updater) => set((state) => {
      state.workspaces = updater(state.workspaces);
    }),
    addWorkspace: (workspace) => set((state) => { state.workspaces.push(workspace); }),
    removeWorkspace: (id) => set((state) => {
      state.workspaces = state.workspaces.filter((w) => w.id !== id);
    }),

    // Issues
    setIssues: (issues) => set((state) => { state.issues = issues; }),
    updateIssues: (updater) => set((state) => {
      state.issues = updater(state.issues);
    }),
    addIssue: (issue) => set((state) => { state.issues.push(issue); }),
    updateIssue: (id, updates) => set((state) => {
      const index = state.issues.findIndex((i) => i.id === id);
      if (index !== -1) {
        state.issues[index] = { ...state.issues[index], ...updates };
      }
    }),
    removeIssue: (id) => set((state) => {
      state.issues = state.issues.filter((i) => i.id !== id);
    }),

    // Tasks
    setTasks: (tasks) => set((state) => { state.tasks = tasks; }),
    updateTasks: (updater) => set((state) => {
      state.tasks = updater(state.tasks);
    }),
    addTask: (task) => set((state) => {
      if (!state.tasks.some((t) => t.id === task.id)) {
        state.tasks.push(task);
      }
    }),
    updateTask: (id, updates) => set((state) => {
      const index = state.tasks.findIndex((t) => t.id === id);
      if (index !== -1) {
        state.tasks[index] = { ...state.tasks[index], ...updates };
      }
    }),
    removeTask: (id) => set((state) => {
      state.tasks = state.tasks.filter((t) => t.id !== id);
    }),

    // Artifacts
    setArtifacts: (artifacts) => set((state) => { state.artifacts = artifacts; }),

    // Execution Processes
    setExecutionProcesses: (processes) => set((state) => {
      state.executionProcesses = processes;
    }),
    updateExecutionProcess: (id, updates) => set((state) => {
      if (state.executionProcesses[id]) {
        state.executionProcesses[id] = { ...state.executionProcesses[id], ...updates };
      }
    }),
    addExecutionProcess: (process) => set((state) => {
      state.executionProcesses[process.id] = process;
    }),
    setSelectedProcessId: (id) => set((state) => { state.selectedProcessId = id; }),
    setOptimisticProcess: (process) => set((state) => { state.optimisticProcess = process; }),
    clearOptimisticProcess: () => set((state) => { state.optimisticProcess = null; }),

    // Logs & Messages
    setProcessLogs: (logs) => set((state) => { state.processLogs = logs; }),
    setProcessMessages: (messages) => set((state) => { state.processMessages = messages; }),
    appendProcessMessage: (message) => set((state) => {
      const index = state.processMessages.findIndex((m) => m.id === message.id);
      if (index !== -1) {
        state.processMessages[index] = message;
      } else {
        state.processMessages.push(message);
      }
    }),
    appendProcessLog: (log) => set((state) => {
      const key = log.id || `${log.created_at}-${log.stream}-${log.content}`;
      if (!state.processLogs.some((l) => (l.id || `${l.created_at}-${l.stream}-${l.content}`) === key)) {
        state.processLogs.push(log);
      }
    }),

    // Help Requests
    setHelpRequests: (requests) => set((state) => { state.helpRequests = requests; }),

    // Approvals
    setPendingApprovals: (approvals) => set((state) => { state.pendingApprovals = approvals; }),
    updatePendingApprovals: (updater) => set((state) => {
      state.pendingApprovals = updater(state.pendingApprovals);
    }),
    removeApproval: (id) => set((state) => {
      state.pendingApprovals = state.pendingApprovals.filter((a) => a.id !== id);
    }),

    // Runtime Catalog
    setRuntimeCatalog: (catalog) => set((state) => { state.runtimeCatalog = catalog; }),

    // Loading states
    setIsLoadingWorkspaces: (loading) => set((state) => { state.isLoadingWorkspaces = loading; }),
    setIsLoadingIssues: (loading) => set((state) => { state.isLoadingIssues = loading; }),
    setIsLoadingLogs: (loading) => set((state) => { state.isLoadingLogs = loading; }),
    setIsLoadingMessages: (loading) => set((state) => { state.isLoadingMessages = loading; }),
    setIsLoadingProcess: (loading) => set((state) => { state.isLoadingProcess = loading; }),

    // Connection
    setIsConnected: (connected) => set((state) => { state.isConnected = connected; }),
    setWasConnected: (wasConnected) => set((state) => { state.wasConnected = wasConnected; }),
    setConnectionWarning: (warning) => set((state) => { state.connectionWarning = warning; }),

    // Error
    setError: (error) => set((state) => { state.error = error; }),

    // Transitions
    setIsTransitioningToArchitecture: (transitioning) => set((state) => {
      state.isTransitioningToArchitecture = transitioning;
    }),
    setIsTransitioningToDevelopment: (transitioning) => set((state) => {
      state.isTransitioningToDevelopment = transitioning;
    }),
    setIsTransitioningToTesting: (transitioning) => set((state) => {
      state.isTransitioningToTesting = transitioning;
    }),
    setIsRunning: (running) => set((state) => { state.isRunning = running; }),

    // Last event
    setLastEvent: (event) => set((state) => { state.lastEvent = event; }),

    // Async Actions
    loadProjects: async () => {
      try {
        const projects = await listProjects();
        set((state) => { state.projects = projects; });
      } catch (err) {
        set((state) => { state.error = err instanceof Error ? err.message : 'Failed to load projects'; });
      }
    },

    loadProject: async (id) => {
      try {
        const project = await getProject(id);
        set((state) => { state.currentProject = project; });
      } catch (err) {
        set((state) => { state.error = err instanceof Error ? err.message : 'Failed to load project'; });
      }
    },

    loadWorkspaces: async (projectId) => {
      set((state) => { state.isLoadingWorkspaces = true; });
      try {
        const workspaces = await getWorkspaces(projectId);
        set((state) => { state.workspaces = workspaces; });
      } catch (err) {
        set((state) => { state.error = err instanceof Error ? err.message : 'Failed to load workspaces'; });
      } finally {
        set((state) => { state.isLoadingWorkspaces = false; });
      }
    },

    loadWorkspaceData: async (workspaceId) => {
      set((state) => { state.isLoadingIssues = true; });
      try {
        const [iss, tks] = await Promise.all([
          getCodexIssues(workspaceId),
          getCodexTasks(workspaceId, null),
        ]);
        set((state) => {
          state.issues = iss;
          state.tasks = tks;
        });

        const helpResults = await Promise.allSettled(
          tks.map((task) => getTaskHelpRequests(task.id))
        );
        const hrs: HelpRequest[] = [];
        for (const result of helpResults) {
          if (result.status === 'fulfilled') {
            hrs.push(...result.value);
          }
        }
        set((state) => { state.helpRequests = hrs; });
      } catch (err) {
        set((state) => { state.error = err instanceof Error ? err.message : 'Failed to load workspace data'; });
      } finally {
        set((state) => { state.isLoadingIssues = false; });
      }
    },

    loadIssueArtifacts: async (issueId) => {
      try {
        const artifacts = await getCodexIssueArtifacts(issueId);
        set((state) => { state.artifacts = artifacts; });
      } catch {
        set((state) => { state.artifacts = []; });
      }
    },

    loadPendingApprovals: async () => {
      try {
        const res = await getPendingApprovals();
        set((state) => { state.pendingApprovals = res.pending; });
      } catch {
        set((state) => { state.pendingApprovals = []; });
      }
    },

    loadRuntimeCatalog: async () => {
      try {
        const catalog = await getRuntimeCatalog();
        set((state) => { state.runtimeCatalog = catalog; });
      } catch {
        set((state) => { state.runtimeCatalog = null; });
      }
    },

    // Phase transition buttons all call the Conductor restart endpoint;
    // Conductor decides which agent to dispatch next. The `phase` arg only
    // updates the issue's display label so existing UI labels keep working.
    transitionToArchitecture: async (issueId) => {
      await startGraphForIssue(get, set, 'isTransitioningToArchitecture', issueId, 'architecture');
    },
    transitionToDevelopment: async (issueId) => {
      await startGraphForIssue(get, set, 'isTransitioningToDevelopment', issueId, 'development');
    },
    transitionToTesting: async (issueId) => {
      await startGraphForIssue(get, set, 'isTransitioningToTesting', issueId, 'testing');
    },

    sendMessage: async (taskId, content, mode) => {
      try {
        let result: SendMessageResult;
        if (mode === 'refine') {
          result = await refineCodexTask(taskId, content);
          set((state) => { state.lastResolvedMode = null; });
        } else if (mode === 'chat') {
          result = await chatCodexTask(taskId, content);
          set((state) => { state.lastResolvedMode = null; });
        } else {
          result = await sendCodexTask(taskId, content);
          if (result?.resolved_mode) set((state) => { state.lastResolvedMode = result.resolved_mode ?? null; });
        }

        if (result?.message) get().appendProcessMessage(result.message as CodexTaskMessage);
        if (result?.assistant_message) get().appendProcessMessage(result.assistant_message as CodexTaskMessage);
        
        if (result?.execution_process) {
          get().setOptimisticProcess(result.execution_process as ExecutionProcess);
          get().setSelectedProcessId(result.execution_process.id);
        }
      } catch (err) {
        set((state) => { state.error = err instanceof Error ? err.message : 'Failed to send message'; });
        throw err;
      }
    },

    // Reset
    resetWorkspaceState: () => set((state) => {
      state.view = 'home';
      state.currentWorkspaceId = null;
      state.currentIssueId = null;
      state.currentTaskId = null;
      state.workspaces = [];
      state.issues = [];
      state.tasks = [];
      state.artifacts = [];
      state.helpRequests = [];
      state.selectedProcessId = null;
      state.optimisticProcess = null;
      state.processLogs = [];
      state.processMessages = [];
    }),

    reset: () => set(() => ({ ...initialState })),
  }))
);

// Selectors
export const selectCurrentWorkspace = (state: WorkbenchState) =>
  state.workspaces.find((w) => w.id === state.currentWorkspaceId) ?? null;

export const selectCurrentIssue = (state: WorkbenchState) =>
  state.issues.find((i) => i.id === state.currentIssueId) ?? null;

export const selectCurrentTask = (state: WorkbenchState) =>
  state.tasks.find((t) => t.id === state.currentTaskId) ?? null;

export const selectCurrentIssueTasks = (state: WorkbenchState) =>
  state.currentIssueId ? state.tasks.filter((t) => t.issue_id === state.currentIssueId) : [];

export const selectSelectedProcess = (state: WorkbenchState): ExecutionProcess | null => {
  if (!state.selectedProcessId) return null;
  return (
    state.executionProcesses[state.selectedProcessId] ??
    (state.optimisticProcess?.id === state.selectedProcessId ? state.optimisticProcess : null)
  );
};

export const selectExecutionProcessesList = (state: WorkbenchState): ExecutionProcess[] =>
  Object.values(state.executionProcesses).sort((a, b) => {
    const aTime = Date.parse(a.created_at || a.started_at || a.updated_at || "") || 0;
    const bTime = Date.parse(b.created_at || b.started_at || b.updated_at || "") || 0;
    return bTime - aTime;
  });
