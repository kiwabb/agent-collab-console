"use client";

import { Plus, Trash2 } from "lucide-react";

import { useI18n } from "@/providers/I18nProvider";

import type { RuntimeBehaviorRule, RuntimePredicate } from "../runtime/types";
import { StructuredPrototypeRuleExpressionEditor } from "./StructuredPrototypeRuleExpressionEditor";
import {
  createStructuredPrototypeRulePredicate,
  structuredPrototypeRuleExpressionType,
  type StructuredPrototypeRulePredicateKind,
} from "./structuredPrototypeRuleDraft";
import type { StructuredPrototypeDocument } from "./types";

interface Props {
  document: StructuredPrototypeDocument;
  trigger: RuntimeBehaviorRule["trigger"];
  guard: RuntimePredicate | null;
  disabled: boolean;
  onChange: (guard: RuntimePredicate | null) => void;
}

type PredicateEditorProps = {
  document: StructuredPrototypeDocument;
  trigger: RuntimeBehaviorRule["trigger"];
  predicate: RuntimePredicate;
  disabled: boolean;
  onChange: (predicate: RuntimePredicate) => void;
  onRemove: (() => void) | null;
};

const CONTROL_CLASS =
  "min-h-9 w-full rounded-md border border-border-muted bg-surface px-2 text-xs text-foreground outline-none focus:border-primary disabled:cursor-not-allowed disabled:opacity-45";
const LABEL_CLASS = "grid gap-1 text-[11px] font-semibold text-text-secondary";
const PREDICATE_KINDS: StructuredPrototypeRulePredicateKind[] = [
  "roleIs",
  "formValid",
  "compare",
  "all",
];

function PredicateEditor({
  document,
  trigger,
  predicate,
  disabled,
  onChange,
  onRemove,
}: PredicateEditorProps) {
  const { t } = useI18n();
  return (
    <div className="grid gap-2 border-l border-border-subtle pl-2">
      <div className="flex items-end gap-2">
        <label className={`${LABEL_CLASS} min-w-0 flex-1`}>
          <span>{t("prototype.structured.rule.guard.type")}</span>
          <select
            className={CONTROL_CLASS}
            value={predicate.kind}
            disabled={disabled}
            onChange={(event) => {
              const next = createStructuredPrototypeRulePredicate(
                document,
                trigger,
                event.currentTarget.value as StructuredPrototypeRulePredicateKind,
              );
              if (next !== null) onChange(next);
            }}
          >
            {PREDICATE_KINDS.map((kind) => (
              <option key={kind} value={kind}>
                {t(`prototype.structured.rule.guard.${kind}`)}
              </option>
            ))}
          </select>
        </label>
        {onRemove !== null && (
          <button
            type="button"
            className="inline-flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-md border border-border-muted text-text-secondary hover:bg-surface-hover hover:text-danger disabled:cursor-not-allowed disabled:opacity-45"
            aria-label={t("prototype.structured.rule.guard.remove")}
            title={t("prototype.structured.rule.guard.remove")}
            disabled={disabled}
            onClick={onRemove}
          >
            <Trash2 size={14} aria-hidden />
          </button>
        )}
      </div>

      {predicate.kind === "roleIs" && (
        <label className={LABEL_CLASS}>
          <span>{t("prototype.structured.rule.role")}</span>
          <select
            className={CONTROL_CLASS}
            value={predicate.roleId}
            disabled={disabled}
            onChange={(event) => onChange({ kind: "roleIs", roleId: event.currentTarget.value })}
          >
            {!document.runtime.roles.some((role) => role.id === predicate.roleId) && (
              <option value={predicate.roleId}>{predicate.roleId}</option>
            )}
            {document.runtime.roles.map((role) => (
              <option key={role.id} value={role.id}>
                {role.label}
              </option>
            ))}
          </select>
        </label>
      )}

      {predicate.kind === "formValid" && (
        <label className={LABEL_CLASS}>
          <span>{t("prototype.structured.rule.form")}</span>
          <select
            className={CONTROL_CLASS}
            value={predicate.formId}
            disabled={disabled}
            onChange={(event) => onChange({ kind: "formValid", formId: event.currentTarget.value })}
          >
            {!document.runtime.forms.some((form) => form.id === predicate.formId) && (
              <option value={predicate.formId}>{predicate.formId}</option>
            )}
            {document.runtime.forms.map((form) => (
              <option key={form.id} value={form.id}>
                {form.key}
              </option>
            ))}
          </select>
        </label>
      )}

      {predicate.kind === "compare" && (
        <div className="grid gap-2">
          <label className={LABEL_CLASS}>
            <span>{t("prototype.structured.rule.guard.operator")}</span>
            <select
              className={CONTROL_CLASS}
              value={predicate.operator}
              disabled={disabled}
              onChange={(event) =>
                onChange({
                  ...predicate,
                  operator: event.currentTarget.value as "eq" | "ne",
                })
              }
            >
              <option value="eq">{t("prototype.structured.rule.guard.eq")}</option>
              <option value="ne">{t("prototype.structured.rule.guard.ne")}</option>
            </select>
          </label>
          <StructuredPrototypeRuleExpressionEditor
            document={document}
            trigger={trigger}
            expression={predicate.left}
            expectedType={null}
            expectedEntitySchemaId={null}
            allowNull
            disabled={disabled}
            label={t("prototype.structured.rule.guard.left")}
            onChange={(left) => onChange({ ...predicate, left })}
          />
          <StructuredPrototypeRuleExpressionEditor
            document={document}
            trigger={trigger}
            expression={predicate.right}
            expectedType={structuredPrototypeRuleExpressionType(document, trigger, predicate.left)}
            expectedEntitySchemaId={null}
            allowNull
            disabled={disabled}
            label={t("prototype.structured.rule.guard.right")}
            onChange={(right) => onChange({ ...predicate, right })}
          />
        </div>
      )}

      {predicate.kind === "all" && (
        <div className="grid gap-3">
          {predicate.items.map((item, index) => (
            <PredicateEditor
              key={index}
              document={document}
              trigger={trigger}
              predicate={item}
              disabled={disabled}
              onChange={(nextItem) =>
                onChange({
                  kind: "all",
                  items: predicate.items.map((current, itemIndex) =>
                    itemIndex === index ? nextItem : current,
                  ),
                })
              }
              onRemove={() =>
                onChange({
                  kind: "all",
                  items: predicate.items.filter((_item, itemIndex) => itemIndex !== index),
                })
              }
            />
          ))}
          <button
            type="button"
            className="inline-flex min-h-9 cursor-pointer items-center justify-center gap-1 rounded-md border border-border-muted px-2 text-[11px] font-semibold text-foreground hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-45"
            disabled={disabled || predicate.items.length >= 20}
            onClick={() => {
              const item = createStructuredPrototypeRulePredicate(document, trigger, "roleIs");
              if (item !== null) onChange({ kind: "all", items: [...predicate.items, item] });
            }}
          >
            <Plus size={13} aria-hidden />
            {t("prototype.structured.rule.guard.add")}
          </button>
        </div>
      )}
    </div>
  );
}

export function StructuredPrototypeRuleGuardEditor({
  document,
  trigger,
  guard,
  disabled,
  onChange,
}: Props) {
  const { t } = useI18n();
  return (
    <section className="grid gap-3 border-t border-border-subtle px-3 py-3">
      <label className={LABEL_CLASS}>
        <span>{t("prototype.structured.rule.guard.title")}</span>
        <select
          className={CONTROL_CLASS}
          value={guard?.kind ?? "none"}
          disabled={disabled}
          onChange={(event) => {
            if (event.currentTarget.value === "none") {
              onChange(null);
              return;
            }
            const next = createStructuredPrototypeRulePredicate(
              document,
              trigger,
              event.currentTarget.value as StructuredPrototypeRulePredicateKind,
            );
            if (next !== null) onChange(next);
          }}
        >
          <option value="none">{t("prototype.structured.rule.guard.none")}</option>
          {PREDICATE_KINDS.map((kind) => (
            <option key={kind} value={kind}>
              {t(`prototype.structured.rule.guard.${kind}`)}
            </option>
          ))}
        </select>
      </label>
      {guard !== null && (
        <PredicateEditor
          document={document}
          trigger={trigger}
          predicate={guard}
          disabled={disabled}
          onChange={onChange}
          onRemove={null}
        />
      )}
    </section>
  );
}
