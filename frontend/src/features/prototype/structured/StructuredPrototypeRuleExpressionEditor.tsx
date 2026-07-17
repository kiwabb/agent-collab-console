"use client";

import { useI18n } from "@/providers/I18nProvider";

import type {
  RuntimeBehaviorRule,
  RuntimeEntityRefExpression,
  RuntimeValue,
  RuntimeValueExpression,
  RuntimeValueType,
} from "../runtime/types";
import {
  createStructuredPrototypeRuleExpression,
  createStructuredPrototypeRuleRuntimeValue,
  structuredPrototypeRuleFixtureEntityIds,
  structuredPrototypeRuleEventSchemaId,
  structuredPrototypeRuleExpressionKinds,
  type StructuredPrototypeRuleExpressionKind,
} from "./structuredPrototypeRuleDraft";
import type { StructuredPrototypeDocument } from "./types";

interface Props {
  document: StructuredPrototypeDocument;
  trigger: RuntimeBehaviorRule["trigger"];
  expression: RuntimeValueExpression;
  expectedType: RuntimeValueType | null;
  expectedEntitySchemaId: string | null;
  allowNull: boolean;
  disabled: boolean;
  label: string;
  onChange: (expression: RuntimeValueExpression) => void;
}

type RuntimeValueEditorProps = {
  document: StructuredPrototypeDocument;
  value: RuntimeValue;
  expectedType: RuntimeValueType | null;
  expectedEntitySchemaId: string | null;
  allowNull: boolean;
  disabled: boolean;
  onChange: (value: RuntimeValue) => void;
};

const CONTROL_CLASS =
  "min-h-9 w-full rounded-md border border-border-muted bg-surface px-2 text-xs text-foreground outline-none focus:border-primary disabled:cursor-not-allowed disabled:opacity-45";
const LABEL_CLASS = "grid gap-1 text-[11px] font-semibold text-text-secondary";

const VALUE_TYPES: RuntimeValueType[] = [
  "null",
  "boolean",
  "integer",
  "string",
  "enum",
  "entityRef",
];

function includeCurrent<T extends string>(values: readonly T[], current: T): T[] {
  return values.includes(current) ? values.slice() : [current, ...values];
}

function RuntimeValueEditor({
  document,
  value,
  expectedType,
  expectedEntitySchemaId,
  allowNull,
  disabled,
  onChange,
}: RuntimeValueEditorProps) {
  const { t } = useI18n();
  const creatableTypes = (
    expectedType === null
      ? VALUE_TYPES.filter((type) => allowNull || type !== "null")
      : [expectedType, ...(allowNull ? (["null"] as const) : [])]
  ).filter(
    (type) =>
      createStructuredPrototypeRuleRuntimeValue(
        document,
        type,
        type === "entityRef" ? expectedEntitySchemaId : null,
      ) !== null,
  );
  const allowedTypes = includeCurrent(creatableTypes, value.type);
  const entitySchemas = document.runtime.entitySchemas.filter(
    (schema) =>
      (expectedEntitySchemaId === null || schema.id === expectedEntitySchemaId) &&
      structuredPrototypeRuleFixtureEntityIds(document, schema.id).length > 0,
  );

  return (
    <div className="grid grid-cols-2 gap-2">
      <label className={LABEL_CLASS}>
        <span>{t("prototype.structured.rule.value.type")}</span>
        <select
          className={CONTROL_CLASS}
          value={value.type}
          disabled={disabled}
          onChange={(event) => {
            const type = event.currentTarget.value as RuntimeValueType;
            const next = createStructuredPrototypeRuleRuntimeValue(
              document,
              type,
              type === "entityRef" ? expectedEntitySchemaId : null,
            );
            if (next !== null) onChange(next);
          }}
        >
          {allowedTypes.map((type) => (
            <option key={type} value={type}>
              {t(`prototype.structured.rule.value.${type}`)}
            </option>
          ))}
        </select>
      </label>

      {value.type === "boolean" && (
        <label className={LABEL_CLASS}>
          <span>{t("prototype.structured.rule.value.value")}</span>
          <select
            className={CONTROL_CLASS}
            value={String(value.value)}
            disabled={disabled}
            onChange={(event) =>
              onChange({ type: "boolean", value: event.currentTarget.value === "true" })
            }
          >
            <option value="true">{t("prototype.structured.rule.value.true")}</option>
            <option value="false">{t("prototype.structured.rule.value.false")}</option>
          </select>
        </label>
      )}

      {value.type === "integer" && (
        <label className={LABEL_CLASS}>
          <span>{t("prototype.structured.rule.value.value")}</span>
          <input
            className={CONTROL_CLASS}
            type="number"
            step={1}
            value={value.value}
            disabled={disabled}
            onChange={(event) => {
              const next = Number(event.currentTarget.value);
              if (Number.isSafeInteger(next)) onChange({ type: "integer", value: next });
            }}
          />
        </label>
      )}

      {(value.type === "string" || value.type === "enum") && (
        <label className={LABEL_CLASS}>
          <span>{t("prototype.structured.rule.value.value")}</span>
          <input
            className={CONTROL_CLASS}
            type="text"
            maxLength={value.type === "enum" ? 64 : 8_000}
            value={value.value}
            disabled={disabled}
            onChange={(event) => onChange({ type: value.type, value: event.currentTarget.value })}
          />
        </label>
      )}

      {value.type === "entityRef" && (
        <>
          <label className={LABEL_CLASS}>
            <span>{t("prototype.structured.rule.value.schema")}</span>
            <select
              className={CONTROL_CLASS}
              value={value.schemaId}
              disabled={disabled}
              onChange={(event) => {
                const schemaId = event.currentTarget.value;
                const entityId = structuredPrototypeRuleFixtureEntityIds(document, schemaId)[0];
                if (entityId === undefined) {
                  throw new Error("selected entity schema has no runtime fixture entity");
                }
                onChange({
                  type: "entityRef",
                  schemaId,
                  entityId,
                });
              }}
            >
              {!entitySchemas.some((schema) => schema.id === value.schemaId) && (
                <option value={value.schemaId}>{value.schemaId}</option>
              )}
              {entitySchemas.map((schema) => (
                <option key={schema.id} value={schema.id}>
                  {schema.key}
                </option>
              ))}
            </select>
          </label>
          <label className={LABEL_CLASS}>
            <span>{t("prototype.structured.rule.value.entity")}</span>
            <select
              className={CONTROL_CLASS}
              value={value.entityId}
              disabled={disabled}
              onChange={(event) => onChange({ ...value, entityId: event.currentTarget.value })}
            >
              {value.entityId === "" && (
                <option value="">{t("prototype.structured.rule.selectPlaceholder")}</option>
              )}
              {!structuredPrototypeRuleFixtureEntityIds(document, value.schemaId).includes(
                value.entityId,
              ) &&
                value.entityId !== "" && <option value={value.entityId}>{value.entityId}</option>}
              {structuredPrototypeRuleFixtureEntityIds(document, value.schemaId).map((entityId) => (
                <option key={entityId} value={entityId}>
                  {entityId}
                </option>
              ))}
            </select>
          </label>
        </>
      )}
    </div>
  );
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

function schemaIdForReference(
  document: StructuredPrototypeDocument,
  trigger: RuntimeBehaviorRule["trigger"],
  reference: RuntimeEntityRefExpression,
): string | null {
  if (reference.kind === "eventEntityRef") {
    return structuredPrototypeRuleEventSchemaId(document, trigger);
  }
  return (
    document.runtime.variables.find((variable) => variable.id === reference.variableId)
      ?.entitySchemaId ?? null
  );
}

export function StructuredPrototypeRuleExpressionEditor({
  document,
  trigger,
  expression,
  expectedType,
  expectedEntitySchemaId,
  allowNull,
  disabled,
  label,
  onChange,
}: Props) {
  const { t } = useI18n();
  const expressionKinds = includeCurrent(
    structuredPrototypeRuleExpressionKinds(document, trigger, expectedType, expectedEntitySchemaId),
    expression.kind,
  );
  const compatibleVariables = document.runtime.variables.filter(
    (variable) =>
      (expectedType === null || variable.valueType === expectedType) &&
      (expectedType !== "entityRef" ||
        expectedEntitySchemaId === null ||
        variable.entitySchemaId === expectedEntitySchemaId),
  );

  return (
    <div className="grid gap-2 border-l border-border-subtle pl-2">
      <label className={LABEL_CLASS}>
        <span>{label}</span>
        <select
          className={CONTROL_CLASS}
          value={expression.kind}
          disabled={disabled}
          onChange={(event) => {
            const next = createStructuredPrototypeRuleExpression(
              document,
              trigger,
              event.currentTarget.value as StructuredPrototypeRuleExpressionKind,
              expectedType,
              expectedEntitySchemaId,
            );
            if (next !== null) onChange(next);
          }}
        >
          {expressionKinds.map((kind) => (
            <option key={kind} value={kind}>
              {t(`prototype.structured.rule.expression.${kind}`)}
            </option>
          ))}
        </select>
      </label>

      {expression.kind === "literal" && (
        <RuntimeValueEditor
          document={document}
          value={expression.value}
          expectedType={expectedType}
          expectedEntitySchemaId={expectedEntitySchemaId}
          allowNull={allowNull}
          disabled={disabled}
          onChange={(value) => onChange({ kind: "literal", value })}
        />
      )}

      {expression.kind === "variable" && (
        <label className={LABEL_CLASS}>
          <span>{t("prototype.structured.rule.variable")}</span>
          <select
            className={CONTROL_CLASS}
            value={expression.variableId}
            disabled={disabled}
            onChange={(event) =>
              onChange({ kind: "variable", variableId: event.currentTarget.value })
            }
          >
            {!compatibleVariables.some((variable) => variable.id === expression.variableId) && (
              <option value={expression.variableId}>{expression.variableId}</option>
            )}
            {compatibleVariables.map((variable) => (
              <option key={variable.id} value={variable.id}>
                {variable.key}
              </option>
            ))}
          </select>
        </label>
      )}

      {expression.kind === "formField" && (
        <div className="grid grid-cols-2 gap-2">
          <label className={LABEL_CLASS}>
            <span>{t("prototype.structured.rule.form")}</span>
            <select
              className={CONTROL_CLASS}
              value={expression.formId}
              disabled={disabled}
              onChange={(event) => {
                const form = document.runtime.forms.find(
                  (candidate) => candidate.id === event.currentTarget.value,
                );
                const field = form?.fields.find(
                  (candidate) => expectedType === null || candidate.valueType === expectedType,
                );
                if (form !== undefined && field !== undefined) {
                  onChange({ kind: "formField", formId: form.id, fieldId: field.id });
                }
              }}
            >
              {!document.runtime.forms.some((form) => form.id === expression.formId) && (
                <option value={expression.formId}>{expression.formId}</option>
              )}
              {document.runtime.forms
                .filter((form) =>
                  form.fields.some(
                    (field) => expectedType === null || field.valueType === expectedType,
                  ),
                )
                .map((form) => (
                  <option key={form.id} value={form.id}>
                    {form.key}
                  </option>
                ))}
            </select>
          </label>
          <label className={LABEL_CLASS}>
            <span>{t("prototype.structured.rule.field")}</span>
            <select
              className={CONTROL_CLASS}
              value={expression.fieldId}
              disabled={disabled}
              onChange={(event) => onChange({ ...expression, fieldId: event.currentTarget.value })}
            >
              {!document.runtime.forms
                .find((form) => form.id === expression.formId)
                ?.fields.some((field) => field.id === expression.fieldId) && (
                <option value={expression.fieldId}>{expression.fieldId}</option>
              )}
              {document.runtime.forms
                .find((form) => form.id === expression.formId)
                ?.fields.filter(
                  (field) => expectedType === null || field.valueType === expectedType,
                )
                .map((field) => (
                  <option key={field.id} value={field.id}>
                    {field.key}
                  </option>
                ))}
            </select>
          </label>
        </div>
      )}

      {expression.kind === "eventEntityRef" && (
        <p className="text-[11px] leading-4 text-text-muted">
          {t("prototype.structured.rule.expression.eventContext")}
        </p>
      )}

      {expression.kind === "entityField" && (
        <div className="grid gap-2">
          <div className="grid grid-cols-2 gap-2">
            <label className={LABEL_CLASS}>
              <span>{t("prototype.structured.rule.entityReference")}</span>
              <select
                className={CONTROL_CLASS}
                value={entityReferenceToken(expression.entityRef)}
                disabled={disabled}
                onChange={(event) => {
                  const entityRef = entityReferenceFromToken(event.currentTarget.value);
                  if (entityRef === null) return;
                  const schemaId = schemaIdForReference(document, trigger, entityRef);
                  const field = document.runtime.entitySchemas
                    .find((schema) => schema.id === schemaId)
                    ?.fields.find(
                      (candidate) =>
                        (expectedType === null || candidate.valueType === expectedType) &&
                        createStructuredPrototypeRuleRuntimeValue(document, candidate.valueType) !==
                          null,
                    );
                  if (field === undefined) return;
                  const fallback = createStructuredPrototypeRuleRuntimeValue(
                    document,
                    field.valueType,
                  );
                  if (fallback === null) return;
                  onChange({
                    kind: "entityField",
                    entityRef,
                    fieldId: field.id,
                    fallback,
                  });
                }}
              >
                {expression.entityRef.kind === "eventEntityRef" &&
                  structuredPrototypeRuleEventSchemaId(document, trigger) === null && (
                    <option value="event">
                      {t("prototype.structured.rule.expression.eventEntityRef")}
                    </option>
                  )}
                {structuredPrototypeRuleEventSchemaId(document, trigger) !== null && (
                  <option value="event">
                    {t("prototype.structured.rule.expression.eventEntityRef")}
                  </option>
                )}
                {document.runtime.variables
                  .filter(
                    (variable) =>
                      variable.valueType === "entityRef" && variable.entitySchemaId !== null,
                  )
                  .map((variable) => (
                    <option key={variable.id} value={`variable:${variable.id}`}>
                      {variable.key}
                    </option>
                  ))}
              </select>
            </label>
            <label className={LABEL_CLASS}>
              <span>{t("prototype.structured.rule.field")}</span>
              <select
                className={CONTROL_CLASS}
                value={expression.fieldId}
                disabled={disabled}
                onChange={(event) => {
                  const fieldId = event.currentTarget.value;
                  const schemaId = schemaIdForReference(document, trigger, expression.entityRef);
                  const field = document.runtime.entitySchemas
                    .find((schema) => schema.id === schemaId)
                    ?.fields.find((candidate) => candidate.id === fieldId);
                  if (field === undefined) return;
                  const fallback = createStructuredPrototypeRuleRuntimeValue(
                    document,
                    field.valueType,
                  );
                  if (fallback === null) return;
                  onChange({
                    ...expression,
                    fieldId,
                    fallback,
                  });
                }}
              >
                {!document.runtime.entitySchemas
                  .find(
                    (schema) =>
                      schema.id === schemaIdForReference(document, trigger, expression.entityRef),
                  )
                  ?.fields.some((field) => field.id === expression.fieldId) && (
                  <option value={expression.fieldId}>{expression.fieldId}</option>
                )}
                {document.runtime.entitySchemas
                  .find(
                    (schema) =>
                      schema.id === schemaIdForReference(document, trigger, expression.entityRef),
                  )
                  ?.fields.filter(
                    (field) =>
                      (expectedType === null || field.valueType === expectedType) &&
                      createStructuredPrototypeRuleRuntimeValue(document, field.valueType) !== null,
                  )
                  .map((field) => (
                    <option key={field.id} value={field.id}>
                      {field.key}
                    </option>
                  ))}
              </select>
            </label>
          </div>
          <RuntimeValueEditor
            document={document}
            value={expression.fallback}
            expectedType={
              document.runtime.entitySchemas
                .find(
                  (schema) =>
                    schema.id === schemaIdForReference(document, trigger, expression.entityRef),
                )
                ?.fields.find((field) => field.id === expression.fieldId)?.valueType ?? null
            }
            expectedEntitySchemaId={null}
            allowNull
            disabled={disabled}
            onChange={(fallback) => onChange({ ...expression, fallback })}
          />
        </div>
      )}
    </div>
  );
}
