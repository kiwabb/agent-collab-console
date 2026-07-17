"use client";

import { useMemo, useState } from "react";
import { Loader2, Save, Trash2, X } from "lucide-react";

import { useI18n } from "@/providers/I18nProvider";

import { StructuredPrototypeRuleEffectsEditor } from "./StructuredPrototypeRuleEffectsEditor";
import { StructuredPrototypeRuleGuardEditor } from "./StructuredPrototypeRuleGuardEditor";
import {
  buildStructuredPrototypeRuleDefinition,
  createStructuredPrototypeRuleDraft,
  structuredPrototypeRuleInspectorStateKey,
  structuredPrototypeRuleTriggerCandidates,
  validateStructuredPrototypeRuleDraft,
  type StructuredPrototypeRuleDraft,
  type StructuredPrototypeRuleInspectorSelection,
} from "./structuredPrototypeRuleDraft";
import type {
  StructuredPrototypeBehaviorRuleDefinition,
  StructuredPrototypeDocument,
} from "./types";

interface Props {
  document: StructuredPrototypeDocument;
  selection: StructuredPrototypeRuleInspectorSelection | null;
  disabled: boolean;
  saving: boolean;
  error: string | null;
  onCreate: (newRuleKey: string, definition: StructuredPrototypeBehaviorRuleDefinition) => void;
  onReplace: (ruleId: string, definition: StructuredPrototypeBehaviorRuleDefinition) => void;
  onRemove: (ruleId: string) => void;
  onCancel: () => void;
}

type FormProps = Omit<Props, "selection"> & {
  selection: StructuredPrototypeRuleInspectorSelection;
  initialDraft: StructuredPrototypeRuleDraft;
};

const CONTROL_CLASS =
  "min-h-9 w-full rounded-md border border-border-muted bg-surface px-2 text-xs text-foreground outline-none focus:border-primary disabled:cursor-not-allowed disabled:opacity-45";
const LABEL_CLASS = "grid gap-1 text-[11px] font-semibold text-text-secondary";

function RuleInspectorForm({
  document,
  selection,
  initialDraft,
  disabled,
  saving,
  error,
  onCreate,
  onReplace,
  onRemove,
  onCancel,
}: FormProps) {
  const { t } = useI18n();
  const [draft, setDraft] = useState(initialDraft);
  const [pendingTriggerNodeId, setPendingTriggerNodeId] = useState(
    initialDraft.trigger?.nodeId ?? "",
  );
  const editingRuleId = selection.kind === "existingRule" ? selection.rule.id : null;
  const sourcePageId = selection.kind === "pendingConnection" ? selection.sourcePageId : null;
  const triggerCandidates = useMemo(
    () => structuredPrototypeRuleTriggerCandidates(document, sourcePageId),
    [document, sourcePageId],
  );
  const triggerNodes = Array.from(
    new Map(
      triggerCandidates.map((candidate) => [
        candidate.nodeId,
        { nodeId: candidate.nodeId, nodeName: candidate.nodeName, pageId: candidate.pageId },
      ]),
    ).values(),
  );
  const triggerEvents = triggerCandidates.filter(
    (candidate) => candidate.nodeId === pendingTriggerNodeId,
  );
  const issues = useMemo(
    () => validateStructuredPrototypeRuleDraft(document, draft, editingRuleId),
    [document, draft, editingRuleId],
  );
  const keyInvalid = issues.some((issue) => issue.path === "key");
  const triggerInvalid = issues.some(
    (issue) => issue.path === "trigger" || issue.path.startsWith("trigger."),
  );
  const locked = disabled || saving;

  return (
    <aside
      className="flex min-h-0 flex-col bg-surface"
      aria-label={t("prototype.structured.rule.title")}
      data-structured-prototype-rule-inspector
    >
      <header className="flex items-start justify-between gap-2 border-b border-border-subtle px-3 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-bold text-foreground">
            {t("prototype.structured.rule.title")}
          </h2>
          <p className="mt-0.5 text-[11px] leading-4 text-text-muted">
            {t(
              selection.kind === "existingRule"
                ? "prototype.structured.rule.editing"
                : "prototype.structured.rule.creating",
            )}
          </p>
        </div>
        <button
          type="button"
          className="inline-flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-md border border-border-muted text-text-secondary hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-45"
          aria-label={t("prototype.structured.rule.cancel")}
          title={t("prototype.structured.rule.cancel")}
          disabled={saving}
          onClick={onCancel}
        >
          <X size={15} aria-hidden />
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <section className="grid gap-3 px-3 py-3">
          <label className={LABEL_CLASS}>
            <span>{t("prototype.structured.rule.key")}</span>
            <input
              className={CONTROL_CLASS}
              type="text"
              maxLength={64}
              spellCheck={false}
              value={draft.key}
              disabled={locked}
              aria-invalid={keyInvalid}
              onChange={(event) =>
                setDraft((current) => ({ ...current, key: event.currentTarget.value }))
              }
            />
          </label>
          <label className="flex min-h-9 cursor-pointer items-center justify-between gap-3 text-xs font-semibold text-foreground">
            <span>{t("prototype.structured.rule.enabled")}</span>
            <input
              className="size-4 accent-primary"
              type="checkbox"
              checked={draft.enabled}
              disabled={locked}
              onChange={(event) =>
                setDraft((current) => ({ ...current, enabled: event.currentTarget.checked }))
              }
            />
          </label>
        </section>

        <section className="grid gap-3 border-t border-border-subtle px-3 py-3">
          <h3 className="text-xs font-bold text-foreground">
            {t("prototype.structured.rule.trigger.title")}
          </h3>
          <label className={LABEL_CLASS}>
            <span>{t("prototype.structured.rule.trigger.node")}</span>
            <select
              className={CONTROL_CLASS}
              value={pendingTriggerNodeId}
              disabled={locked}
              aria-invalid={triggerInvalid}
              onChange={(event) => {
                setPendingTriggerNodeId(event.currentTarget.value);
                setDraft((current) => ({ ...current, trigger: null }));
              }}
            >
              <option value="">{t("prototype.structured.rule.selectPlaceholder")}</option>
              {pendingTriggerNodeId !== "" &&
                !triggerNodes.some((node) => node.nodeId === pendingTriggerNodeId) && (
                  <option value={pendingTriggerNodeId}>{pendingTriggerNodeId}</option>
                )}
              {triggerNodes.map((node) => {
                const page = document.pages.find((candidate) => candidate.id === node.pageId);
                return (
                  <option key={node.nodeId} value={node.nodeId}>
                    {page?.title ?? node.pageId} / {node.nodeName}
                  </option>
                );
              })}
            </select>
          </label>
          <label className={LABEL_CLASS}>
            <span>{t("prototype.structured.rule.trigger.event")}</span>
            <select
              className={CONTROL_CLASS}
              value={draft.trigger?.nodeId === pendingTriggerNodeId ? draft.trigger.event : ""}
              disabled={locked || pendingTriggerNodeId === ""}
              aria-invalid={triggerInvalid}
              onChange={(event) => {
                const triggerEvent = event.currentTarget.value;
                if (
                  triggerEvent !== "click" &&
                  triggerEvent !== "submit" &&
                  triggerEvent !== "rowActivated"
                ) {
                  setDraft((current) => ({ ...current, trigger: null }));
                  return;
                }
                setDraft((current) => ({
                  ...current,
                  trigger: {
                    kind: "nodeEvent",
                    nodeId: pendingTriggerNodeId,
                    event: triggerEvent,
                  },
                }));
              }}
            >
              <option value="">{t("prototype.structured.rule.selectPlaceholder")}</option>
              {draft.trigger !== null &&
                draft.trigger.nodeId === pendingTriggerNodeId &&
                !triggerEvents.some((candidate) => candidate.event === draft.trigger?.event) && (
                  <option value={draft.trigger.event}>
                    {t(`prototype.structured.rule.trigger.${draft.trigger.event}`)}
                  </option>
                )}
              {triggerEvents.map((candidate) => (
                <option key={candidate.event} value={candidate.event}>
                  {t(`prototype.structured.rule.trigger.${candidate.event}`)}
                </option>
              ))}
            </select>
          </label>
          {triggerCandidates.length === 0 && (
            <p className="border-l-2 border-status-awaiting pl-2 text-[11px] leading-4 text-text-secondary">
              {t("prototype.structured.rule.noEligibleTrigger")}
            </p>
          )}
        </section>

        {draft.trigger !== null && (
          <>
            <StructuredPrototypeRuleGuardEditor
              document={document}
              trigger={draft.trigger}
              guard={draft.guard}
              disabled={locked}
              onChange={(guard) => setDraft((current) => ({ ...current, guard }))}
            />
            <StructuredPrototypeRuleEffectsEditor
              document={document}
              trigger={draft.trigger}
              effects={draft.effects}
              list="primary"
              disabled={locked}
              onChange={(effects) => setDraft((current) => ({ ...current, effects }))}
            />
            <StructuredPrototypeRuleEffectsEditor
              document={document}
              trigger={draft.trigger}
              effects={draft.guardFalseEffects}
              list="guardFalse"
              disabled={locked}
              onChange={(guardFalseEffects) =>
                setDraft((current) => ({ ...current, guardFalseEffects }))
              }
            />
          </>
        )}
      </div>

      <footer className="grid gap-2 border-t border-border-subtle px-3 py-3">
        {error !== null && (
          <p
            className="border-l-2 border-danger pl-2 text-[11px] leading-4 text-danger"
            role="alert"
          >
            {error}
          </p>
        )}
        {issues[0] !== undefined && (
          <p
            className="border-l-2 border-status-awaiting pl-2 text-[11px] leading-4 text-text-secondary"
            role="status"
          >
            {t(`prototype.structured.rule.validation.${issues[0].code}`)} {issues[0].path}
          </p>
        )}
        <div className="flex items-center gap-2">
          {selection.kind === "existingRule" && (
            <button
              type="button"
              className="inline-flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-md border border-danger/40 text-danger hover:bg-danger/10 disabled:cursor-not-allowed disabled:opacity-45"
              aria-label={t("prototype.structured.rule.remove")}
              title={t("prototype.structured.rule.remove")}
              disabled={locked}
              onClick={() => onRemove(selection.rule.id)}
            >
              <Trash2 size={14} aria-hidden />
            </button>
          )}
          <button
            type="button"
            className="inline-flex min-h-9 flex-1 cursor-pointer items-center justify-center gap-1.5 rounded-md border border-border-muted px-3 text-xs font-semibold text-foreground hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-45"
            disabled={saving}
            onClick={onCancel}
          >
            {t("prototype.structured.rule.cancel")}
          </button>
          <button
            type="button"
            className="inline-flex min-h-9 flex-1 cursor-pointer items-center justify-center gap-1.5 rounded-md bg-primary px-3 text-xs font-bold text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-45"
            disabled={locked || issues.length > 0}
            onClick={() => {
              const definition = buildStructuredPrototypeRuleDefinition(draft);
              if (definition === null) return;
              if (selection.kind === "existingRule") {
                onReplace(selection.rule.id, definition);
              } else {
                onCreate(definition.key, definition);
              }
            }}
          >
            {saving ? (
              <Loader2 className="motion-essential animate-spin" size={14} aria-hidden />
            ) : (
              <Save size={14} aria-hidden />
            )}
            {t(
              saving
                ? "prototype.structured.rule.saving"
                : selection.kind === "existingRule"
                  ? "prototype.structured.rule.save"
                  : "prototype.structured.rule.create",
            )}
          </button>
        </div>
      </footer>
    </aside>
  );
}

export function StructuredPrototypeRuleInspector(props: Props) {
  const { t } = useI18n();
  if (props.selection === null) {
    return (
      <aside
        className="grid min-h-0 place-items-center border-l border-border-subtle bg-surface p-4 text-center text-xs text-text-muted"
        aria-label={t("prototype.structured.rule.title")}
        data-structured-prototype-rule-inspector
      >
        {t("prototype.structured.rule.empty")}
      </aside>
    );
  }
  const initialDraft = createStructuredPrototypeRuleDraft(props.document, props.selection);
  if (initialDraft === null) {
    return (
      <aside
        className="grid min-h-0 place-items-center border-l border-border-subtle bg-surface p-4 text-center"
        aria-label={t("prototype.structured.rule.title")}
        data-structured-prototype-rule-inspector
      >
        <div className="grid gap-3">
          <p className="text-xs leading-5 text-text-secondary">
            {t("prototype.structured.rule.noEligibleTrigger")}
          </p>
          <button
            type="button"
            className="min-h-9 rounded-md border border-border-muted px-3 text-xs font-semibold text-foreground hover:bg-surface-hover"
            onClick={props.onCancel}
          >
            {t("prototype.structured.rule.cancel")}
          </button>
        </div>
      </aside>
    );
  }
  return (
    <RuleInspectorForm
      key={structuredPrototypeRuleInspectorStateKey(props.selection)}
      {...props}
      selection={props.selection}
      initialDraft={initialDraft}
    />
  );
}
