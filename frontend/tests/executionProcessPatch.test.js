import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { applyExecutionProcessPatch } from '../src/hooks/applyExecutionProcessPatch.js';
import {
  mergeTaskConversationLogs,
  mergeTaskConversationMessages,
} from '../src/hooks/taskConversationDetailUtils.js';

test('applyExecutionProcessPatch stores data under execution_processes', () => {
  const next = applyExecutionProcessPatch(
    { execution_processes: {} },
    [{ op: 'add', path: '/execution_processes/exec-1', value: { id: 'exec-1', status: 'Running' } }],
  );

  assert.equal(next.execution_processes['exec-1'].status, 'Running');
});

test('mergeTaskConversationMessages preserves history across multiple execution processes', () => {
  const messages = mergeTaskConversationMessages([
    [
      { id: 'm1', role: 'user', content: 'first', created_at: '2026-04-18T10:00:00Z' },
      { id: 'm2', role: 'assistant', content: 'reply1', created_at: '2026-04-18T10:01:00Z' },
    ],
    [
      { id: 'm3', role: 'user', content: 'follow up', created_at: '2026-04-18T10:02:00Z' },
      { id: 'm4', role: 'assistant', content: 'reply2', created_at: '2026-04-18T10:03:00Z' },
    ],
  ]);

  assert.deepEqual(messages.map((message) => message.id), ['m1', 'm2', 'm3', 'm4']);
});

test('mergeTaskConversationLogs deduplicates repeated realtime log entries', () => {
  const logs = mergeTaskConversationLogs([
    [
      { id: 'l1', content: 'first', created_at: '2026-04-18T10:00:00Z' },
    ],
    [
      { id: 'l1', content: 'first', created_at: '2026-04-18T10:00:00Z' },
      { id: 'l2', content: 'second', created_at: '2026-04-18T10:01:00Z' },
    ],
  ]);

  assert.deepEqual(logs.map((log) => log.id), ['l1', 'l2']);
});

test('App no longer references deprecated execution process selection state names', () => {
  const testDir = path.dirname(fileURLToPath(import.meta.url));
  const sourcePath = path.resolve(testDir, '../src/App.jsx');
  const source = fs.readFileSync(sourcePath, 'utf8');

  assert.equal(source.includes('setCurrentExecutionProcessId'), false);
  assert.equal(source.includes('currentExecutionProcessId'), false);
});

test('App uses grouped task selection state', () => {
  const testDir = path.dirname(fileURLToPath(import.meta.url));
  const sourcePath = path.resolve(testDir, '../src/App.jsx');
  const source = fs.readFileSync(sourcePath, 'utf8');

  assert.equal(source.includes('currentRuntimeSelectionId'), true);
  assert.equal(source.includes('setCurrentRuntimeSelectionId'), true);
});

test('App uses workspace naming for selected workspace state and handlers', () => {
  const testDir = path.dirname(fileURLToPath(import.meta.url));
  const sourcePath = path.resolve(testDir, '../src/App.jsx');
  const source = fs.readFileSync(sourcePath, 'utf8');

  assert.equal(source.includes('const [selectedWorkspace, setSelectedWorkspace]'), true);
  assert.equal(source.includes('const [workspaces, setWorkspaces]'), true);
  assert.equal(source.includes('function WorkspaceTaskWorkspace('), true);
  assert.equal(source.includes('handleCreateWorkspace'), true);
  assert.equal(source.includes('handleSelectWorkspace'), true);
  assert.equal(source.includes('handleDeleteWorkspace'), true);
  assert.equal(source.includes('handleDeleteAllWorkspaces'), true);
  assert.equal(source.includes('Select a workspace from the sidebar or create a new one to get started.'), true);
  assert.equal(source.includes('const [codexSession, setCodexSession]'), false);
  assert.equal(source.includes('const [codexSessions, setCodexSessions]'), false);
});

test('api exposes workspace-first wrapper names with legacy aliases preserved', () => {
  const testDir = path.dirname(fileURLToPath(import.meta.url));
  const sourcePath = path.resolve(testDir, '../src/api.js');
  const source = fs.readFileSync(sourcePath, 'utf8');

  assert.equal(source.includes('export async function getWorkspaces()'), true);
  assert.equal(source.includes('export async function createWorkspace(title, cwd = "")'), true);
  assert.equal(source.includes('export async function getWorkspace(workspaceId)'), true);
  assert.equal(source.includes('export async function deleteWorkspace(workspaceId)'), true);
  assert.equal(source.includes('export async function deleteAllWorkspaces()'), true);
  assert.equal(source.includes('`${API_BASE}/codex/workspaces`'), true);
  assert.equal(source.includes('`${API_BASE}/codex/workspaces/${workspaceId}`'), true);
  assert.equal(source.includes('export const getCodexSessions = getWorkspaces;'), true);
  assert.equal(source.includes('export const createCodexSession = createWorkspace;'), true);
  assert.equal(source.includes('export const getCodexSession = getWorkspace;'), true);
  assert.equal(source.includes('export const deleteCodexSession = deleteWorkspace;'), true);
  assert.equal(source.includes('export const deleteAllCodexSessions = deleteAllWorkspaces;'), true);
});

test('execution process provider and hook use workspaceId naming while preserving session route', () => {
  const testDir = path.dirname(fileURLToPath(import.meta.url));
  const providerPath = path.resolve(testDir, '../src/providers/ExecutionProcessesProvider.jsx');
  const hookPath = path.resolve(testDir, '../src/hooks/useExecutionProcesses.js');
  const providerSource = fs.readFileSync(providerPath, 'utf8');
  const hookSource = fs.readFileSync(hookPath, 'utf8');

  assert.equal(providerSource.includes('export function ExecutionProcessesProvider({ workspaceId, children })'), true);
  assert.equal(providerSource.includes('useExecutionProcesses(workspaceId)'), true);
  assert.equal(providerSource.includes('Boolean(workspaceId)'), true);
  assert.equal(providerSource.includes('sessionId'), false);

  assert.equal(hookSource.includes('export function useExecutionProcesses(workspaceId)'), true);
  assert.equal(hookSource.includes('if (!workspaceId)'), true);
  assert.equal(hookSource.includes('/api/workspaces/${workspaceId}/execution_processes/ws'), true);
  assert.equal(hookSource.includes('sessionId'), false);
});
