"use client";

import { useMemo } from "react";
import { GitBranch, ListTree } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { useI18n } from "@/providers/I18nProvider";
import type { AuditLog } from "@/lib/api";
import { cn } from "@/lib/utils";
import { buildAuditRoleGroups, type AuditRoleTurnGroup } from "./auditRoleChains";

interface Props {
  items: AuditLog[];
}

function hasValue(value: unknown): boolean {
  if (value == null) return false;
  if (typeof value === "string") return value.length > 0;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "object") return Object.keys(value).length > 0;
  return true;
}

function formatValue(value: unknown): string {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function turnLabel(
  t: (key: string, params?: Record<string, string | number>) => string,
  turn: AuditRoleTurnGroup,
): string {
  if (turn.turnIndex == null) return t("auditLog.roleChain.unscoped");
  return t("auditLog.roleChain.turn", { turn: turn.turnIndex + 1 });
}

function DetailBlock({ label, value }: { label: string; value: unknown }) {
  if (!hasValue(value)) return null;
  return (
    <div className="space-y-1">
      <div className="text-text-faint text-[10px] font-bold tracking-wider uppercase">{label}</div>
      <pre className="border-border-subtle bg-surface-input/40 text-text-secondary max-h-64 overflow-auto rounded-lg border p-2 font-mono text-[10px] leading-relaxed break-words whitespace-pre-wrap">
        {formatValue(value)}
      </pre>
    </div>
  );
}

export function AuditRoleChainView({ items }: Props) {
  const { t } = useI18n();
  const groups = useMemo(() => buildAuditRoleGroups(items), [items]);

  if (groups.length === 0) return null;

  return (
    <section data-density="audit-role-chain" className="space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-text-primary flex items-center gap-2 text-sm font-semibold">
            <GitBranch size={15} className="text-brand" />
            {t("auditLog.roleChain.title")}
          </div>
          <p className="text-text-muted mt-1 text-xs">{t("auditLog.roleChain.description")}</p>
        </div>
        <Badge variant="outline" className="border-brand/30 bg-brand/10 text-brand shrink-0">
          {t("auditLog.roleChain.groupCount", { count: groups.length })}
        </Badge>
      </div>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        {groups.map((group) => (
          <article
            key={group.role}
            className="border-border-subtle bg-surface-raised/70 rounded-xl border p-3"
          >
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="text-text-primary truncate text-sm font-semibold">
                  {group.roleLabel}
                </div>
                <div className="text-text-faint font-mono text-[10px]">{group.role}</div>
              </div>
              <span className="border-border-subtle text-text-muted shrink-0 rounded-full border px-2 py-0.5 text-[10px]">
                {t("auditLog.roleChain.entryCount", { count: group.entries.length })}
              </span>
            </div>

            <div className="mt-3 space-y-3">
              {group.turns.map((turn) => (
                <div key={turn.key} className="space-y-2">
                  <div className="text-text-muted flex items-center gap-2 text-[11px] font-semibold">
                    <ListTree size={13} className="text-text-faint" />
                    <span>{turnLabel(t, turn)}</span>
                    {turn.conductorTaskId && (
                      <span className="text-text-faint truncate font-mono text-[10px]">
                        {turn.conductorTaskId}
                      </span>
                    )}
                  </div>

                  <ol className="space-y-1.5">
                    {turn.entries.map(({ entry, summary }) => {
                      const hasInput = hasValue(entry.call_input);
                      const hasOutput = hasValue(entry.call_output);
                      return (
                        <li
                          key={entry.id}
                          data-density="audit-role-chain-entry"
                          className="border-border-subtle bg-surface-input/30 rounded-lg border px-2.5 py-2"
                        >
                          <div className="flex items-center gap-2">
                            <Badge
                              variant="outline"
                              className="border-border-subtle bg-surface-raised text-text-muted shrink-0 text-[10px] uppercase"
                            >
                              {t(`auditLog.category.${entry.category}` as never) || entry.category}
                            </Badge>
                            {entry.call_name && (
                              <span className="text-text-faint max-w-[120px] shrink-0 truncate font-mono text-[10px]">
                                {entry.call_name}
                              </span>
                            )}
                            {entry.status && (
                              <span
                                className={cn(
                                  "shrink-0 rounded-full border px-1.5 py-0.5 text-[10px] font-bold uppercase",
                                  entry.status === "error" || entry.error
                                    ? "border-status-failed/30 text-status-failed"
                                    : "border-status-done/30 text-status-done",
                                )}
                              >
                                {entry.status}
                              </span>
                            )}
                          </div>
                          <div className="text-text-secondary mt-1 truncate text-xs">{summary}</div>

                          <details className="mt-1.5">
                            <summary className="text-text-faint hover:text-text-muted cursor-pointer text-[10px] select-none">
                              {t("auditLog.roleChain.details")}
                            </summary>
                            <div className="mt-2 space-y-2">
                              <DetailBlock
                                label={t("auditLog.roleChain.input")}
                                value={entry.call_input}
                              />
                              <DetailBlock
                                label={t("auditLog.roleChain.output")}
                                value={entry.call_output}
                              />
                              {!hasInput && !hasOutput && (
                                <DetailBlock
                                  label={t("auditLog.roleChain.raw")}
                                  value={entry.payload_json}
                                />
                              )}
                            </div>
                          </details>
                        </li>
                      );
                    })}
                  </ol>
                </div>
              ))}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
