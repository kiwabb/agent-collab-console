import type { AuditLog } from "@/lib/api/audit";

export interface AuditRoleChainEntry {
  entry: AuditLog;
  summary: string;
}

export interface AuditRoleTurnGroup {
  key: string;
  turnIndex: number | null;
  conductorTaskId: string | null;
  entries: AuditRoleChainEntry[];
}

export interface AuditRoleGroup {
  role: string;
  roleLabel: string;
  entries: AuditRoleChainEntry[];
  turns: AuditRoleTurnGroup[];
}

function roleKey(entry: AuditLog): string {
  if (entry.role) return entry.role;
  if (entry.conductor_task_id) return "conductor";
  return "system";
}

function roleLabel(entry: AuditLog, role: string): string {
  if (entry.role_label) return entry.role_label;
  if (role === "conductor") return "Conductor";
  if (role === "system") return "System";
  if (role === "agent") return "Agent";
  return role.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function entrySummary(entry: AuditLog): string {
  return entry.call_summary || entry.error || entry.call_name || entry.actor || entry.category;
}

function createdAtMs(entry: AuditLog): number {
  if (!entry.created_at) return 0;
  const value = new Date(entry.created_at).getTime();
  return Number.isFinite(value) ? value : 0;
}

function compareChainEntries(a: AuditLog, b: AuditLog): number {
  const turnA = a.turn_index ?? Number.MAX_SAFE_INTEGER;
  const turnB = b.turn_index ?? Number.MAX_SAFE_INTEGER;
  if (turnA !== turnB) return turnA - turnB;

  const subA = a.sub_index ?? Number.MAX_SAFE_INTEGER;
  const subB = b.sub_index ?? Number.MAX_SAFE_INTEGER;
  if (subA !== subB) return subA - subB;

  const timeA = createdAtMs(a);
  const timeB = createdAtMs(b);
  if (timeA !== timeB) return timeA - timeB;

  return a.id.localeCompare(b.id);
}

export function buildAuditRoleGroups(items: AuditLog[]): AuditRoleGroup[] {
  const groups = new Map<string, AuditRoleGroup>();
  const ordered = [...items].sort(compareChainEntries);

  for (const entry of ordered) {
    const role = roleKey(entry);
    const existing = groups.get(role);
    const group = existing ?? {
      role,
      roleLabel: roleLabel(entry, role),
      entries: [],
      turns: [],
    };
    const chainEntry = { entry, summary: entrySummary(entry) };
    group.entries.push(chainEntry);

    const turnKey = `${entry.conductor_task_id ?? "taskless"}:${entry.turn_index ?? "unscoped"}`;
    let turn = group.turns.find((candidate) => candidate.key === turnKey);
    if (!turn) {
      turn = {
        key: turnKey,
        turnIndex: entry.turn_index,
        conductorTaskId: entry.conductor_task_id,
        entries: [],
      };
      group.turns.push(turn);
    }
    turn.entries.push(chainEntry);
    groups.set(role, group);
  }

  return [...groups.values()];
}
