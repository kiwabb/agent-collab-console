import type {
  StructuredPrototypeGenerationBlueprint,
  StructuredPrototypeGenerationEffect,
  StructuredPrototypeGenerationExpression,
  StructuredPrototypeGenerationJob,
  StructuredPrototypeGenerationJobStatus,
  StructuredPrototypeGenerationPredicate,
  StructuredPrototypeGenerationRuntimeValue,
  StructuredPrototypeGenerationScenarioStep,
} from "./types";

const ACTIVE_GENERATION_STATUSES = new Set<StructuredPrototypeGenerationJobStatus>([
  "queued",
  "planning",
  "generating",
  "assembling",
  "validating",
  "rendering_preview",
]);

const PROJECT_ANALYSIS_DEFAULT_BRIEF =
  "Analyze the registered project source and generate the smallest coherent editable prototype " +
  "from its routes and pages. Include data models, roles, forms, behaviors, flows, and scenarios " +
  "only when repository code proves they exist.";

export interface StructuredPrototypeGenerationBlueprintScopeGroup {
  key: "roles" | "entities" | "variables" | "forms" | "views" | "behaviors" | "flows" | "scenarios";
  values: string[];
}

export type StructuredPrototypeGenerationSourceExclusion =
  | { kind: "unknown" }
  | { kind: "clean"; sensitive: number }
  | { kind: "dirty"; tracked: number; untracked: number; sensitive: number };

function formatRuntimeValue(value: StructuredPrototypeGenerationRuntimeValue): string {
  if (value.type === "null") return "null";
  return `${value.type}:${JSON.stringify(value.value)}`;
}

function formatEntityRefExpression(
  expression: Extract<
    StructuredPrototypeGenerationExpression,
    { kind: "entityField" }
  >["entityRef"],
): string {
  return expression.kind === "variable" ? `variable:${expression.variableKey}` : "eventEntityRef";
}

function formatExpression(expression: StructuredPrototypeGenerationExpression): string {
  switch (expression.kind) {
    case "literal":
      return formatRuntimeValue(expression.value);
    case "variable":
      return `variable:${expression.variableKey}`;
    case "formField":
      return `form:${expression.formKey}.${expression.fieldKey}`;
    case "eventEntityRef":
      return "eventEntityRef";
    case "entityField":
      return `entity:${expression.schemaKey}.${expression.fieldKey}(${formatEntityRefExpression(expression.entityRef)}) fallback=${formatRuntimeValue(expression.fallback)}`;
  }
}

function formatPredicate(predicate: StructuredPrototypeGenerationPredicate): string {
  switch (predicate.kind) {
    case "all":
      return `all(${predicate.items.map(formatPredicate).join(", ")})`;
    case "roleIs":
      return `role=${predicate.roleKey}`;
    case "formValid":
      return `formValid:${predicate.formKey}`;
    case "compare":
      return `${formatExpression(predicate.left)} ${predicate.operator} ${formatExpression(predicate.right)}`;
  }
}

function formatAssignments(
  assignments: Array<{ fieldKey: string; value: StructuredPrototypeGenerationExpression }>,
): string {
  return assignments
    .map((assignment) => `${assignment.fieldKey}=${formatExpression(assignment.value)}`)
    .join(", ");
}

function formatEffect(effect: StructuredPrototypeGenerationEffect): string {
  switch (effect.kind) {
    case "setVariable":
      return `set ${effect.variableKey}=${formatExpression(effect.value)}`;
    case "validateForm":
      return `validate ${effect.formKey}`;
    case "createEntity":
      return `create ${effect.schemaKey} -> ${effect.resultVariableKey} {${formatAssignments(effect.values)}}`;
    case "updateEntity":
      return `update ${effect.schemaKey}(${formatEntityRefExpression(effect.entityRef)}) {${formatAssignments(effect.updates)}}`;
    case "navigate":
      return `navigate ${effect.targetPageKey}`;
    case "notify":
      return `notify ${effect.level}:${JSON.stringify(effect.message)}`;
  }
}

function formatScenarioStep(step: StructuredPrototypeGenerationScenarioStep): string {
  switch (step.kind) {
    case "commitFormField":
      return `commit ${step.pageKey}/${step.formKey}.${step.fieldKey}=${formatRuntimeValue(step.value)} -> ${step.expectedOutcome}`;
    case "activateBehavior":
      return `activate ${step.behaviorIntentKey} -> ${step.expectedOutcome}`;
    case "activateEntityBehavior":
      return `activate ${step.behaviorIntentKey} with ${step.schemaKey}.${step.entityKey} -> ${step.expectedOutcome}`;
    case "switchRole":
      return `switchRole ${step.roleKey} -> ${step.expectedOutcome}`;
  }
}

export function structuredPrototypeGenerationBlueprintScope(
  blueprint: StructuredPrototypeGenerationBlueprint,
): StructuredPrototypeGenerationBlueprintScopeGroup[] {
  const groups: StructuredPrototypeGenerationBlueprintScopeGroup[] = [
    {
      key: "roles",
      values: blueprint.roleIntents.map((role) => `${role.label} (${role.key})`),
    },
    {
      key: "entities",
      values: blueprint.entityIntents.map(
        (entity) =>
          `${entity.key} (${entity.fields
            .map((field) => `${field.key}:${field.valueType}${field.nullable ? "?" : ""}`)
            .join(", ")})`,
      ),
    },
    {
      key: "variables",
      values: blueprint.variableIntents.map(
        (variable) =>
          `${variable.key}:${variable.valueType}${variable.nullable ? "?" : ""}${variable.entitySchemaKey ? `<${variable.entitySchemaKey}>` : ""} = ${formatRuntimeValue(variable.defaultValue)}`,
      ),
    },
    {
      key: "forms",
      values: blueprint.formIntents.map(
        (form) =>
          `${form.key} @ ${form.pageKey} (${form.fields
            .map(
              (field) =>
                `${field.key}:${field.valueType}${field.required ? " required" : ""}${field.minInteger === null ? "" : ` min=${field.minInteger}`} initial=${formatRuntimeValue(field.initialValue)}`,
            )
            .join(", ")})`,
      ),
    },
    {
      key: "views",
      values: blueprint.viewBindingIntents.map((binding) => {
        if (binding.target === "textContent") {
          return `${binding.key} @ ${binding.pageKey}: text=${formatExpression(binding.value)}`;
        }
        if (binding.target === "visibility") {
          return `${binding.key} @ ${binding.pageKey}: visible when ${formatPredicate(binding.predicate)}`;
        }
        return `${binding.key} @ ${binding.pageKey}: rows=${binding.schemaKey} sort=${binding.sortFieldKey ?? "none"}/${binding.sortDirection}`;
      }),
    },
    {
      key: "behaviors",
      values: blueprint.behaviorIntents.map(
        (behavior) =>
          `${behavior.key} @ ${behavior.sourcePageKey} | guard: ${behavior.guard ? formatPredicate(behavior.guard) : "none"} | effects: ${behavior.effects.map(formatEffect).join("; ") || "none"} | guard-false: ${behavior.guardFalseEffects.map(formatEffect).join("; ") || "none"}`,
      ),
    },
    {
      key: "flows",
      values: blueprint.flowIntents.map(
        (flow) =>
          `${flow.key}: ${flow.sourcePageKey} -> ${flow.targetPageKey} (${flow.behaviorIntentKey})`,
      ),
    },
    {
      key: "scenarios",
      values: blueprint.scenarioIntents.map((scenario) => {
        const initialVariables = scenario.initialVariables
          .map((item) => `${item.variableKey}=${formatRuntimeValue(item.value)}`)
          .join(", ");
        const fixtures = scenario.entityFixtures
          .flatMap((fixture) =>
            fixture.entities.map(
              (entity) =>
                `${fixture.schemaKey}.${entity.key}{${entity.fields
                  .map((field) => `${field.fieldKey}=${formatRuntimeValue(field.value)}`)
                  .join(", ")}}`,
            ),
          )
          .join(", ");
        const steps = scenario.scriptedSteps
          .map((step, index) => `${index + 1}. ${formatScenarioStep(step)}`)
          .join("; ");
        const milestones = scenario.milestones
          .map((milestone) => {
            const values = milestone.variableValues
              .map((item) => `${item.variableKey}=${formatRuntimeValue(item.value)}`)
              .join(", ");
            const entityValues = milestone.entityFieldValues
              .map(
                (item) =>
                  `${item.schemaKey}.${item.entityKey}.${item.fieldKey}=${formatRuntimeValue(item.value)}`,
              )
              .join(", ");
            return `after ${milestone.afterStep}: page=${milestone.currentPageKey ?? "unchanged"}, variables=${values || "none"}, entities=${entityValues || "none"}`;
          })
          .join("; ");
        return `${scenario.key}: role=${scenario.actorRoleKey}, start=${scenario.startPageKey}, role-switch=${scenario.allowSimulatedRoleSwitch} | initial: ${initialVariables || "none"} | fixtures: ${fixtures || "none"} | steps: ${steps || "none"} | milestones: ${milestones || "none"}`;
      }),
    },
  ];
  return groups.filter((group) => group.values.length > 0);
}

export function isStructuredPrototypeGenerationActive(
  status: StructuredPrototypeGenerationJobStatus,
): boolean {
  return ACTIVE_GENERATION_STATUSES.has(status);
}

export function structuredPrototypeGenerationPercent(
  job: StructuredPrototypeGenerationJob,
): number {
  if (job.total === 0) return 0;
  return Math.round((job.processed / job.total) * 100);
}

export function structuredPrototypeGenerationSourceExclusion(
  job: StructuredPrototypeGenerationJob | null,
): StructuredPrototypeGenerationSourceExclusion {
  if (job === null || job.workingTreeDirty === null || job.excludedSensitiveFileCount === null) {
    return { kind: "unknown" };
  }
  if (!job.workingTreeDirty) {
    return { kind: "clean", sensitive: job.excludedSensitiveFileCount };
  }
  if (job.excludedTrackedChangeCount === null || job.excludedUntrackedCount === null) {
    return { kind: "unknown" };
  }
  return {
    kind: "dirty",
    tracked: job.excludedTrackedChangeCount,
    untracked: job.excludedUntrackedCount,
    sensitive: job.excludedSensitiveFileCount,
  };
}

export function canStartStructuredPrototypeGeneration(
  job: StructuredPrototypeGenerationJob | null,
): boolean {
  return (
    job === null ||
    job.status === "failed" ||
    job.status === "interrupted" ||
    job.status === "cancelled"
  );
}

export function structuredPrototypeGenerationBrief(brief: string): string {
  const trimmed = brief.trim();
  return trimmed || PROJECT_ANALYSIS_DEFAULT_BRIEF;
}

export function nextStructuredPrototypeGenerationPollFailureCount(
  currentFailureCount: number,
  outcome: "success" | "failure",
): number {
  return outcome === "success" ? 0 : currentFailureCount + 1;
}
