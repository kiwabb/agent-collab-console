"use client";

import { useState } from "react";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";

import { useI18n } from "@/providers/I18nProvider";

import type {
  RuntimeBehaviorRule,
  RuntimeEffect,
  RuntimeEntityRefExpression,
  RuntimeValueExpression,
} from "../runtime/types";
import { StructuredPrototypeRuleExpressionEditor } from "./StructuredPrototypeRuleExpressionEditor";
import {
  STRUCTURED_PROTOTYPE_GUARD_FALSE_EFFECT_LIMIT,
  STRUCTURED_PROTOTYPE_PRIMARY_EFFECT_LIMIT,
  createStructuredPrototypeRuleEffect,
  createStructuredPrototypeRuleExpression,
  insertStructuredPrototypeRuleEffect,
  moveStructuredPrototypeRuleEffect,
  removeStructuredPrototypeRuleEffect,
  structuredPrototypeCreateEntitySchemaOptions,
  structuredPrototypeRuleEventSchemaId,
  type StructuredPrototypeRuleEffectKind,
} from "./structuredPrototypeRuleDraft";
import type { StructuredPrototypeDocument } from "./types";

interface Props {
  document: StructuredPrototypeDocument;
  trigger: RuntimeBehaviorRule["trigger"];
  effects: RuntimeEffect[];
  list: "primary" | "guardFalse";
  disabled: boolean;
  onChange: (effects: RuntimeEffect[]) => void;
}

type EffectEditorProps = {
  document: StructuredPrototypeDocument;
  trigger: RuntimeBehaviorRule["trigger"];
  effect: RuntimeEffect;
  index: number;
  count: number;
  disabled: boolean;
  onChange: (effect: RuntimeEffect) => void;
  onMove: (targetIndex: number) => void;
  onRemove: () => void;
};

type AssignmentEditorProps = {
  document: StructuredPrototypeDocument;
  trigger: RuntimeBehaviorRule["trigger"];
  schemaId: string;
  assignments: Array<{ fieldId: string; value: RuntimeValueExpression }>;
  allowEmpty: boolean;
  disabled: boolean;
  onChange: (assignments: Array<{ fieldId: string; value: RuntimeValueExpression }>) => void;
};

const CONTROL_CLASS =
  "min-h-9 w-full rounded-md border border-border-muted bg-surface px-2 text-xs text-foreground outline-none focus:border-primary disabled:cursor-not-allowed disabled:opacity-45";
const LABEL_CLASS = "grid gap-1 text-[11px] font-semibold text-text-secondary";
const EFFECT_KINDS: StructuredPrototypeRuleEffectKind[] = [
  "navigate",
  "notify",
  "setVariable",
  "validateForm",
  "createEntity",
  "updateEntity",
];

function includeCurrent<T extends string>(values: readonly T[], current: T): T[] {
  return values.includes(current) ? values.slice() : [current, ...values];
}

function entityReferenceToken(reference: RuntimeEntityRefExpression): string {
  return reference.kind === "eventEntityRef" ? "event" : `variable:${reference.variableId}`;
}

function entityReferenceFromToken(token: string): RuntimeEntityRefExpression | null {
  if (token === "event") return { kind: "eventEntityRef" };
  if (token.startsWith("variable:")) {
    return { kind: "variable", variableId: token.slice("variable:".length) };
  }
  return null;
}

function AssignmentEditor({
  document,
  trigger,
  schemaId,
  assignments,
  allowEmpty,
  disabled,
  onChange,
}: AssignmentEditorProps) {
  const { t } = useI18n();
  const schema = document.runtime.entitySchemas.find((candidate) => candidate.id === schemaId);
  const availableFields =
    schema?.fields.filter(
      (candidate) =>
        !assignments.some((assignment) => assignment.fieldId === candidate.id) &&
        createStructuredPrototypeRuleExpression(
          document,
          trigger,
          "literal",
          candidate.valueType,
        ) !== null,
    ) ?? [];
  return (
    <div className="grid gap-2 border-t border-border-subtle pt-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-semibold text-text-secondary">
          {t("prototype.structured.rule.effect.assignments")}
        </span>
        <button
          type="button"
          className="inline-flex min-h-8 cursor-pointer items-center justify-center gap-1 rounded-md border border-border-muted px-2 text-[11px] font-semibold text-foreground hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-45"
          disabled={disabled || availableFields.length === 0}
          onClick={() => {
            const field = availableFields[0];
            if (field === undefined) return;
            const value = createStructuredPrototypeRuleExpression(
              document,
              trigger,
              "literal",
              field.valueType,
            );
            if (value !== null) onChange([...assignments, { fieldId: field.id, value }]);
          }}
        >
          <Plus size={12} aria-hidden />
          {t("prototype.structured.rule.effect.addAssignment")}
        </button>
      </div>
      {assignments.map((assignment, index) => {
        const field = schema?.fields.find((candidate) => candidate.id === assignment.fieldId);
        return (
          <div key={`${assignment.fieldId}:${index}`} className="grid gap-2 border-l pl-2">
            <div className="flex items-end gap-2">
              <label className={`${LABEL_CLASS} min-w-0 flex-1`}>
                <span>{t("prototype.structured.rule.field")}</span>
                <select
                  className={CONTROL_CLASS}
                  value={assignment.fieldId}
                  disabled={disabled}
                  onChange={(event) => {
                    const nextField = schema?.fields.find(
                      (candidate) => candidate.id === event.currentTarget.value,
                    );
                    if (nextField === undefined) return;
                    const value = createStructuredPrototypeRuleExpression(
                      document,
                      trigger,
                      "literal",
                      nextField.valueType,
                    );
                    if (value === null) return;
                    onChange(
                      assignments.map((current, assignmentIndex) =>
                        assignmentIndex === index ? { fieldId: nextField.id, value } : current,
                      ),
                    );
                  }}
                >
                  {!schema?.fields.some((candidate) => candidate.id === assignment.fieldId) && (
                    <option value={assignment.fieldId}>{assignment.fieldId}</option>
                  )}
                  {schema?.fields
                    .filter(
                      (candidate) =>
                        candidate.id === assignment.fieldId ||
                        (!assignments.some((current) => current.fieldId === candidate.id) &&
                          createStructuredPrototypeRuleExpression(
                            document,
                            trigger,
                            "literal",
                            candidate.valueType,
                          ) !== null),
                    )
                    .map((candidate) => (
                      <option key={candidate.id} value={candidate.id}>
                        {candidate.key}
                      </option>
                    ))}
                </select>
              </label>
              <button
                type="button"
                className="inline-flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-md border border-border-muted text-text-secondary hover:bg-surface-hover hover:text-danger disabled:cursor-not-allowed disabled:opacity-45"
                aria-label={t("prototype.structured.rule.effect.removeAssignment")}
                title={t("prototype.structured.rule.effect.removeAssignment")}
                disabled={disabled || (!allowEmpty && assignments.length === 1)}
                onClick={() =>
                  onChange(
                    assignments.filter((_current, assignmentIndex) => assignmentIndex !== index),
                  )
                }
              >
                <Trash2 size={13} aria-hidden />
              </button>
            </div>
            <StructuredPrototypeRuleExpressionEditor
              document={document}
              trigger={trigger}
              expression={assignment.value}
              expectedType={field?.valueType ?? null}
              expectedEntitySchemaId={null}
              allowNull={false}
              disabled={disabled}
              label={t("prototype.structured.rule.effect.assignmentValue")}
              onChange={(value) =>
                onChange(
                  assignments.map((current, assignmentIndex) =>
                    assignmentIndex === index ? { ...current, value } : current,
                  ),
                )
              }
            />
          </div>
        );
      })}
    </div>
  );
}

function EffectEditor({
  document,
  trigger,
  effect,
  index,
  count,
  disabled,
  onChange,
  onMove,
  onRemove,
}: EffectEditorProps) {
  const { t } = useI18n();
  const availableKinds = includeCurrent(
    EFFECT_KINDS.filter(
      (kind) => createStructuredPrototypeRuleEffect(document, trigger, kind) !== null,
    ),
    effect.kind,
  );
  const updateEntitySchemas = document.runtime.entitySchemas.filter((schema) => {
    const variableAvailable = document.runtime.variables.some(
      (variable) => variable.valueType === "entityRef" && variable.entitySchemaId === schema.id,
    );
    return (
      variableAvailable || structuredPrototypeRuleEventSchemaId(document, trigger) === schema.id
    );
  });
  const entitySchemas =
    effect.kind === "createEntity"
      ? structuredPrototypeCreateEntitySchemaOptions(document)
      : updateEntitySchemas;

  return (
    <li className="grid gap-2 border-t border-border-subtle py-3 first:border-t-0 first:pt-0">
      <div className="flex items-end gap-1">
        <label className={`${LABEL_CLASS} min-w-0 flex-1`}>
          <span>{t("prototype.structured.rule.effect.number", { number: index + 1 })}</span>
          <select
            className={CONTROL_CLASS}
            value={effect.kind}
            disabled={disabled}
            onChange={(event) => {
              const next = createStructuredPrototypeRuleEffect(
                document,
                trigger,
                event.currentTarget.value as StructuredPrototypeRuleEffectKind,
              );
              if (next !== null) onChange(next);
            }}
          >
            {availableKinds.map((kind) => (
              <option key={kind} value={kind}>
                {t(`prototype.structured.rule.effect.${kind}`)}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="inline-flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-md border border-border-muted text-text-secondary hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-35"
          aria-label={t("prototype.structured.rule.effect.moveUp")}
          title={t("prototype.structured.rule.effect.moveUp")}
          disabled={disabled || index === 0}
          onClick={() => onMove(index - 1)}
        >
          <ArrowUp size={13} aria-hidden />
        </button>
        <button
          type="button"
          className="inline-flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-md border border-border-muted text-text-secondary hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-35"
          aria-label={t("prototype.structured.rule.effect.moveDown")}
          title={t("prototype.structured.rule.effect.moveDown")}
          disabled={disabled || index === count - 1}
          onClick={() => onMove(index + 1)}
        >
          <ArrowDown size={13} aria-hidden />
        </button>
        <button
          type="button"
          className="inline-flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-md border border-border-muted text-text-secondary hover:bg-surface-hover hover:text-danger disabled:cursor-not-allowed disabled:opacity-35"
          aria-label={t("prototype.structured.rule.effect.remove")}
          title={t("prototype.structured.rule.effect.remove")}
          disabled={disabled}
          onClick={onRemove}
        >
          <Trash2 size={13} aria-hidden />
        </button>
      </div>

      {effect.kind === "navigate" && (
        <label className={LABEL_CLASS}>
          <span>{t("prototype.structured.rule.effect.targetPage")}</span>
          <select
            className={CONTROL_CLASS}
            value={effect.targetPageId}
            disabled={disabled}
            onChange={(event) =>
              onChange({ kind: "navigate", targetPageId: event.currentTarget.value })
            }
          >
            {!document.pages.some((page) => page.id === effect.targetPageId) && (
              <option value={effect.targetPageId}>{effect.targetPageId}</option>
            )}
            {document.pages.map((page) => (
              <option key={page.id} value={page.id}>
                {page.title}
              </option>
            ))}
          </select>
        </label>
      )}

      {effect.kind === "notify" && (
        <div className="grid grid-cols-[minmax(90px,0.4fr)_minmax(0,1fr)] gap-2">
          <label className={LABEL_CLASS}>
            <span>{t("prototype.structured.rule.effect.level")}</span>
            <select
              className={CONTROL_CLASS}
              value={effect.level}
              disabled={disabled}
              onChange={(event) =>
                onChange({
                  ...effect,
                  level: event.currentTarget.value as typeof effect.level,
                })
              }
            >
              {(["info", "success", "warning", "error"] as const).map((level) => (
                <option key={level} value={level}>
                  {t(`prototype.structured.rule.effect.level.${level}`)}
                </option>
              ))}
            </select>
          </label>
          <label className={LABEL_CLASS}>
            <span>{t("prototype.structured.rule.effect.message")}</span>
            <input
              className={CONTROL_CLASS}
              type="text"
              maxLength={240}
              value={effect.message}
              disabled={disabled}
              onChange={(event) => onChange({ ...effect, message: event.currentTarget.value })}
            />
          </label>
        </div>
      )}

      {effect.kind === "validateForm" && (
        <label className={LABEL_CLASS}>
          <span>{t("prototype.structured.rule.form")}</span>
          <select
            className={CONTROL_CLASS}
            value={effect.formId}
            disabled={disabled}
            onChange={(event) =>
              onChange({ kind: "validateForm", formId: event.currentTarget.value })
            }
          >
            {!document.runtime.forms.some((form) => form.id === effect.formId) && (
              <option value={effect.formId}>{effect.formId}</option>
            )}
            {document.runtime.forms.map((form) => (
              <option key={form.id} value={form.id}>
                {form.key}
              </option>
            ))}
          </select>
        </label>
      )}

      {effect.kind === "setVariable" && (
        <div className="grid gap-2">
          <label className={LABEL_CLASS}>
            <span>{t("prototype.structured.rule.variable")}</span>
            <select
              className={CONTROL_CLASS}
              value={effect.variableId}
              disabled={disabled}
              onChange={(event) => {
                const variable = document.runtime.variables.find(
                  (candidate) => candidate.id === event.currentTarget.value,
                );
                if (variable === undefined) return;
                const value = createStructuredPrototypeRuleExpression(
                  document,
                  trigger,
                  "literal",
                  variable.valueType,
                  variable.entitySchemaId,
                );
                if (value !== null)
                  onChange({ kind: "setVariable", variableId: variable.id, value });
              }}
            >
              {!document.runtime.variables.some(
                (variable) => variable.id === effect.variableId,
              ) && <option value={effect.variableId}>{effect.variableId}</option>}
              {document.runtime.variables
                .filter(
                  (variable) =>
                    createStructuredPrototypeRuleExpression(
                      document,
                      trigger,
                      "literal",
                      variable.valueType,
                      variable.entitySchemaId,
                    ) !== null,
                )
                .map((variable) => (
                  <option key={variable.id} value={variable.id}>
                    {variable.key}
                  </option>
                ))}
            </select>
          </label>
          <StructuredPrototypeRuleExpressionEditor
            document={document}
            trigger={trigger}
            expression={effect.value}
            expectedType={
              document.runtime.variables.find((variable) => variable.id === effect.variableId)
                ?.valueType ?? null
            }
            expectedEntitySchemaId={
              document.runtime.variables.find((variable) => variable.id === effect.variableId)
                ?.entitySchemaId ?? null
            }
            allowNull={false}
            disabled={disabled}
            label={t("prototype.structured.rule.effect.value")}
            onChange={(value) => onChange({ ...effect, value })}
          />
        </div>
      )}

      {(effect.kind === "createEntity" || effect.kind === "updateEntity") && (
        <div className="grid gap-2">
          <label className={LABEL_CLASS}>
            <span>{t("prototype.structured.rule.value.schema")}</span>
            <select
              className={CONTROL_CLASS}
              value={effect.schemaId}
              disabled={disabled}
              onChange={(event) => {
                const schema = document.runtime.entitySchemas.find(
                  (candidate) => candidate.id === event.currentTarget.value,
                );
                if (schema === undefined) {
                  throw new Error("selected entity schema does not exist");
                }
                const variable = document.runtime.variables.find(
                  (candidate) =>
                    candidate.valueType === "entityRef" && candidate.entitySchemaId === schema.id,
                );
                if (effect.kind === "createEntity") {
                  if (variable === undefined) {
                    throw new Error("createEntity schema has no entityRef result variable");
                  }
                  onChange({
                    kind: "createEntity",
                    schemaId: schema.id,
                    resultVariableId: variable.id,
                    values: [],
                  });
                  return;
                }
                const field = schema.fields.find(
                  (candidate) =>
                    createStructuredPrototypeRuleExpression(
                      document,
                      trigger,
                      "literal",
                      candidate.valueType,
                    ) !== null,
                );
                const value =
                  field === undefined
                    ? null
                    : createStructuredPrototypeRuleExpression(
                        document,
                        trigger,
                        "literal",
                        field.valueType,
                      );
                const eventRefAvailable =
                  structuredPrototypeRuleEventSchemaId(document, trigger) === schema.id;
                if (field !== undefined && value !== null && eventRefAvailable) {
                  onChange({
                    kind: "updateEntity",
                    schemaId: schema.id,
                    entityRef: { kind: "eventEntityRef" },
                    updates: [{ fieldId: field.id, value }],
                  });
                } else if (field !== undefined && value !== null && variable !== undefined) {
                  onChange({
                    kind: "updateEntity",
                    schemaId: schema.id,
                    entityRef: { kind: "variable", variableId: variable.id },
                    updates: [{ fieldId: field.id, value }],
                  });
                }
              }}
            >
              {!entitySchemas.some((schema) => schema.id === effect.schemaId) && (
                <option value={effect.schemaId}>{effect.schemaId}</option>
              )}
              {entitySchemas.map((schema) => (
                <option key={schema.id} value={schema.id}>
                  {schema.key}
                </option>
              ))}
            </select>
          </label>

          {effect.kind === "createEntity" && (
            <label className={LABEL_CLASS}>
              <span>{t("prototype.structured.rule.effect.resultVariable")}</span>
              <select
                className={CONTROL_CLASS}
                value={effect.resultVariableId}
                disabled={disabled}
                onChange={(event) =>
                  onChange({ ...effect, resultVariableId: event.currentTarget.value })
                }
              >
                {!document.runtime.variables.some(
                  (variable) => variable.id === effect.resultVariableId,
                ) && <option value={effect.resultVariableId}>{effect.resultVariableId}</option>}
                {document.runtime.variables
                  .filter(
                    (variable) =>
                      variable.valueType === "entityRef" &&
                      variable.entitySchemaId === effect.schemaId,
                  )
                  .map((variable) => (
                    <option key={variable.id} value={variable.id}>
                      {variable.key}
                    </option>
                  ))}
              </select>
            </label>
          )}

          {effect.kind === "updateEntity" && (
            <label className={LABEL_CLASS}>
              <span>{t("prototype.structured.rule.entityReference")}</span>
              <select
                className={CONTROL_CLASS}
                value={entityReferenceToken(effect.entityRef)}
                disabled={disabled}
                onChange={(event) => {
                  const entityRef = entityReferenceFromToken(event.currentTarget.value);
                  if (entityRef !== null) onChange({ ...effect, entityRef });
                }}
              >
                {structuredPrototypeRuleEventSchemaId(document, trigger) === effect.schemaId && (
                  <option value="event">
                    {t("prototype.structured.rule.expression.eventEntityRef")}
                  </option>
                )}
                {effect.entityRef.kind === "eventEntityRef" &&
                  structuredPrototypeRuleEventSchemaId(document, trigger) !== effect.schemaId && (
                    <option value="event">
                      {t("prototype.structured.rule.expression.eventEntityRef")}
                    </option>
                  )}
                {document.runtime.variables
                  .filter(
                    (variable) =>
                      variable.valueType === "entityRef" &&
                      variable.entitySchemaId === effect.schemaId,
                  )
                  .map((variable) => (
                    <option key={variable.id} value={`variable:${variable.id}`}>
                      {variable.key}
                    </option>
                  ))}
              </select>
            </label>
          )}

          <AssignmentEditor
            document={document}
            trigger={trigger}
            schemaId={effect.schemaId}
            assignments={effect.kind === "createEntity" ? effect.values : effect.updates}
            allowEmpty={effect.kind === "createEntity"}
            disabled={disabled}
            onChange={(assignments) =>
              onChange(
                effect.kind === "createEntity"
                  ? { ...effect, values: assignments }
                  : { ...effect, updates: assignments },
              )
            }
          />
        </div>
      )}
    </li>
  );
}

export function StructuredPrototypeRuleEffectsEditor({
  document,
  trigger,
  effects,
  list,
  disabled,
  onChange,
}: Props) {
  const { t } = useI18n();
  const availableKinds = EFFECT_KINDS.filter(
    (kind) => createStructuredPrototypeRuleEffect(document, trigger, kind) !== null,
  );
  const [newEffectKind, setNewEffectKind] = useState<StructuredPrototypeRuleEffectKind>(
    availableKinds[0] ?? "notify",
  );
  const effectiveNewEffectKind = availableKinds.includes(newEffectKind)
    ? newEffectKind
    : (availableKinds[0] ?? "notify");
  const limit =
    list === "primary"
      ? STRUCTURED_PROTOTYPE_PRIMARY_EFFECT_LIMIT
      : STRUCTURED_PROTOTYPE_GUARD_FALSE_EFFECT_LIMIT;

  return (
    <section className="grid gap-3 border-t border-border-subtle px-3 py-3">
      <div>
        <h3 className="text-xs font-bold text-foreground">
          {t(
            list === "primary"
              ? "prototype.structured.rule.effect.primary"
              : "prototype.structured.rule.effect.guardFalse",
          )}
        </h3>
        <p className="mt-0.5 text-[11px] leading-4 text-text-muted">
          {t("prototype.structured.rule.effect.orderHint")}
        </p>
      </div>
      {effects.length === 0 && (
        <p className="border-l-2 border-border-muted pl-2 text-[11px] leading-4 text-text-muted">
          {t(
            list === "primary"
              ? "prototype.structured.rule.effect.primaryRequired"
              : "prototype.structured.rule.effect.emptyGuardFalse",
          )}
        </p>
      )}
      <ol>
        {effects.map((effect, index) => (
          <EffectEditor
            key={index}
            document={document}
            trigger={trigger}
            effect={effect}
            index={index}
            count={effects.length}
            disabled={disabled}
            onChange={(nextEffect) =>
              onChange(
                effects.map((current, effectIndex) =>
                  effectIndex === index ? nextEffect : current,
                ),
              )
            }
            onMove={(targetIndex) =>
              onChange(moveStructuredPrototypeRuleEffect(effects, index, targetIndex))
            }
            onRemove={() => onChange(removeStructuredPrototypeRuleEffect(effects, index))}
          />
        ))}
      </ol>
      <div className="flex items-end gap-2">
        <label className={`${LABEL_CLASS} min-w-0 flex-1`}>
          <span>{t("prototype.structured.rule.effect.addType")}</span>
          <select
            className={CONTROL_CLASS}
            value={effectiveNewEffectKind}
            disabled={disabled || availableKinds.length === 0}
            onChange={(event) =>
              setNewEffectKind(event.currentTarget.value as StructuredPrototypeRuleEffectKind)
            }
          >
            {availableKinds.map((kind) => (
              <option key={kind} value={kind}>
                {t(`prototype.structured.rule.effect.${kind}`)}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="inline-flex min-h-9 shrink-0 cursor-pointer items-center justify-center gap-1 rounded-md border border-border-muted px-2 text-[11px] font-semibold text-foreground hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-45"
          disabled={disabled || effects.length >= limit || availableKinds.length === 0}
          onClick={() => {
            const effect = createStructuredPrototypeRuleEffect(
              document,
              trigger,
              effectiveNewEffectKind,
            );
            if (effect !== null) {
              onChange(insertStructuredPrototypeRuleEffect(effects, effects.length, effect));
            }
          }}
        >
          <Plus size={13} aria-hidden />
          {t("prototype.structured.rule.effect.add")}
        </button>
      </div>
    </section>
  );
}
