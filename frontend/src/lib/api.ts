// Compatibility entrypoint for legacy "@/lib/api" imports.
//
// Runtime feature code should import domain modules directly from
// "@/lib/api/<domain>". Keep this file as an explicit export map so the
// legacy surface cannot drift into a second implementation of the API client.

export {
  API_BASE,
  WS_BASE,
  apiDedupedRequest,
  apiJsonRequest,
  apiRequest,
  apiRequestOr,
  dedupedFetch,
  formatApiErrorDetail,
  handleResponse,
  jsonRequestInit,
} from "./api/fetch";

export { checkBackendHealth, getCodexStatus, getGlobalEventsStreamUrl } from "./api/health";

export {
  createCodexSession,
  createWorkspace,
  deleteAllCodexSessions,
  deleteAllWorkspaces,
  deleteCodexSession,
  deleteWorkspace,
  getCodexSession,
  getCodexSessions,
  getWorkspace,
  getWorkspaceStreamUrl,
  getWorkspaces,
  sendWorkspaceInput,
  terminateWorkspace,
  updateWorkspace,
} from "./api/workspaces";

export {
  askProjectConductor,
  createProject,
  deleteProject,
  getConductors,
  getProject,
  getProjectAudit,
  getProjectBranches,
  getProjectConductorState,
  getProjectRemoteStatus,
  getProjectRunLogs,
  getProjectRunStatus,
  getProjectStats,
  isProjectRunStartError,
  listProjects,
  pullProject,
  repairProject,
  scheduleProjectConductorReview,
  selectDirectory,
  startProjectConductorLoop,
  startProjectRun,
  startProjectScriptTask,
  stopProjectRun,
  suggestProjectScript,
  updateProject,
} from "./api/projects";
export type { ConductorSession, StartProjectRunResult } from "./api/projects";
export type {
  ProjectEnvListResponse,
  ProjectEnvPutBody,
  ProjectEnvPutBatchBody,
  ProjectEnvPutResponse,
  ProjectEnvVarDisplay,
  ProjectEnvVarEntry,
} from "./types";

export {
  abandonCodexIssue,
  approveCodexIssuePlan,
  bulkDeleteIssues,
  bulkUpdateIssues,
  createCodexIssue,
  createGithubPR,
  deleteCodexIssue,
  duplicateCodexIssue,
  exportCodexIssues,
  finalizeAbandonedCodexIssue,
  forkCodexIssue,
  getCodexIssue,
  getCodexIssueArtifacts,
  getCodexIssueChecklist,
  getCodexIssueDiff,
  getCodexIssues,
  getIssueActivity,
  getIssueArtifactsDownloadUrl,
  getIssueGraphStats,
  getIssuePipelineStages,
  importCodexIssues,
  mergeCodexIssue,
  pinCodexIssue,
  qaReviewCodexIssue,
  refreshGithubPR,
  restoreCodexIssue,
  steerCodexIssue,
  transitionIssueToArchitecture,
  transitionIssueToDevelopment,
  transitionIssueToTesting,
  updateCodexIssue,
  updateCodexIssuePhase,
} from "./api/issues";
export type {
  ActivityEvent,
  ActivityResponse,
  GraphNodeStat,
  GraphNodeSummaryStat,
  GraphStatsResponse,
  IssueChecklist,
  PipelineStage,
  PipelineStagesResponse,
  TransitionIssueToArchitectureResult,
  TransitionIssueToDevelopmentResult,
  TransitionIssueToTestingResult,
} from "./api/issues";

export {
  answerCodexTaskClarification,
  chatCodexTask,
  continueCodexTask,
  createCodexTask,
  deleteCodexTask,
  downloadFile,
  exportCodexTasks,
  getCodexTask,
  getCodexTaskLogs,
  getCodexTaskMessages,
  getCodexTasks,
  getExecutionProcess,
  getExecutionProcessLogs,
  getExecutionProcessMessages,
  getExecutionProcesses,
  getProcessLogsUrl,
  getProcessMessagesUrl,
  getTaskHelpRequests,
  importCodexTasks,
  refineCodexTask,
  requestCodexTaskHelp,
  rerunCodexTask,
  reviewCodexTask,
  runCodexTask,
  sendCodexTask,
  sendCodexTaskMessage,
  submitCodexTask,
  terminateCodexTask,
  updateCodexTask,
  updateCodexTaskExecutor,
} from "./api/tasks";

export {
  createPrototype,
  deletePrototype,
  getPrototype,
  getPrototypeStreamUrl,
  getPrototypeVersion,
  getRegenerateAllStreamUrl,
  listPrototypes,
} from "./api/prototypes";

export { getProjectResume, importProjectResumePdf, saveProjectResume } from "./api/resume";
export type { ProjectResume, ProjectResumeImport } from "./api/resume";

export {
  getRuntimeCatalog,
  testRuntimeExecutor,
  updateRuntimeCatalog,
  validateRuntimeCatalog,
} from "./api/runtime";
export type { TestExecutorRequest } from "./api/runtime";

export {
  getCodexCostStats,
  getCodexStats,
  getIssueBudget,
  getIssueOrchestrationPolicy,
} from "./api/stats";
export type { CodexCostStats } from "./api/stats";

export {
  appendConductorMessage,
  autoStartIssueGraph,
  confirmReplan,
  getAgentMesh,
  getAgentMessages,
  getConductorLog,
  getConductorPhaseEstimates,
  getConductorState,
  getConductorStateLog,
  getConductorTurns,
  getIssueGraph,
  getSubAgentResults,
  listReplanPending,
  pauseConductor,
  planIssue,
  rejectReplan,
  resetIssue,
  restartConductor,
  resumeConductor,
  saveIssueGraph,
  sendConductorMessage,
  startIssueGraph,
} from "./api/conductors";
export type {
  AgentMessage,
  ConductorDecision,
  ConductorPhaseEstimate,
  ConductorStateLogEntry,
  ConductorStatePayload,
  ConductorTurn,
  ReplanPending,
  SubAgentResultPayload,
} from "./api/conductors";

export { createAgent, deleteAgent, getAgent, listAgents, updateAgent } from "./api/agents";

export { getPendingApprovals, resolveApproval } from "./api/approvals";

export { getAuditLog } from "./api/audit";
export type { AuditLog, AuditLogCategory, AuditLogPage } from "./api/audit";

export { getMcpCatalog } from "./api/mcp";
export type {
  McpAvailability,
  McpCatalogResponse,
  McpRecentCall,
  McpRiskLevel,
  McpServerCatalogEntry,
  McpToolCatalogEntry,
} from "./api/mcp";

export {
  fetchSkillContent,
  createSkill,
  createSkillCategory,
  deleteSkill,
  deleteSkillCategory,
  importSkillsExcel,
  importSkillsMarkdown,
  listSkillCategories,
  listSkills,
  translateSkillContent,
} from "./api/skills";
export type { TranslateSkillResult } from "./api/skills";

export {
  deleteTeamNotesBlock,
  getEmbeddingStatus,
  getSimilarIssues,
  getTeamNotes,
  pinTeamNotesBlock,
  restoreTeamNotesBlock,
  searchKnowledge,
  triggerKnowledgeReindex,
} from "./api/knowledge";
export type {
  EmbeddingStatus,
  KnowledgeArtifactHit,
  KnowledgeIssueHit,
  KnowledgeSearchMode,
  KnowledgeSearchResponse,
  KnowledgeSearchScope,
  SimilarIssue,
  TeamNoteBlock,
  TeamNotesResponse,
} from "./api/knowledge";

export {
  getBaselineRun,
  getBenchmarkJob,
  getBenchmarkRun,
  getBenchmarkRunDiff,
  getCalibrationReport,
  listBenchmarkRuns,
  setBaselineRun,
  triggerBenchmarkRun,
} from "./api/benchmarks";
export type { TriggerBenchmarkBody, TriggerBenchmarkResponse } from "./api/benchmarks";
