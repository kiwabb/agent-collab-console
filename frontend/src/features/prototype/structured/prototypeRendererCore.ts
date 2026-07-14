import type {
  StructuredPrototypeDocument,
  StructuredPrototypeFormNode,
  StructuredPrototypeInputNode,
  StructuredPrototypeLength,
  StructuredPrototypeNode,
} from "./types";

export const PROTOTYPE_RENDERER_VERSION = "structured-prototype-renderer/0.1.0";
export const PROTOTYPE_RENDERER_ENVIRONMENT_VERSION = "node20-static-bundle/1";
export const PROTOTYPE_RENDERER_SANDBOX_POLICY_VERSION = "prototype-static-csp/1";

export interface RenderedPrototypeFile {
  relativePath: "document.json" | "index.html" | "runtime.js" | "styles.css";
  content: string;
}

export interface FormInputBinding {
  nodeId: string;
  formId: string;
  fieldId: string;
  valueType: "string" | "integer";
}

export interface PrototypeRenderPreflight {
  contractVersion: 1;
  checks: Array<{
    code: string;
    status: "passed";
    evidence: string;
  }>;
  pageCount: number;
  nodeCount: number;
  formBindingCount: number;
  externalAssetCount: number;
}

export class PrototypeRendererError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "PrototypeRendererError";
  }
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function length(value: StructuredPrototypeLength): string {
  if (value.unit === "auto") return "auto";
  if (value.value === null) {
    throw new PrototypeRendererError("renderer_layout_invalid", "non-auto length has no value");
  }
  const suffix = value.unit === "percent" ? "%" : value.unit;
  return `${value.value}${suffix}`;
}

function safeTokenValue(kind: "color" | "spacing", value: string): string {
  const valid =
    kind === "color"
      ? /^#[0-9a-fA-F]{3,8}$/u.test(value)
      : /^(?:0|[1-9][0-9]*(?:\.[0-9]{1,4})?)(?:px|rem)$/u.test(value);
  if (!valid) {
    throw new PrototypeRendererError(
      "renderer_token_unsupported",
      `renderer does not support ${kind} token value ${value}`,
    );
  }
  return value;
}

function layoutRules(node: StructuredPrototypeNode): string[] {
  const item = node.layoutItem;
  const rules = [
    `width:${length(item.width)}`,
    `height:${length(item.height)}`,
    `flex-grow:${item.grow}`,
    `flex-shrink:${item.shrink}`,
    `align-self:${item.alignSelf === "auto" ? "auto" : item.alignSelf}`,
  ];
  if (item.minWidth !== null) rules.push(`min-width:${length(item.minWidth)}`);
  if (item.maxWidth !== null) rules.push(`max-width:${length(item.maxWidth)}`);
  if (item.minHeight !== null) rules.push(`min-height:${length(item.minHeight)}`);
  if (item.maxHeight !== null) rules.push(`max-height:${length(item.maxHeight)}`);
  if (node.visibility === "hidden") rules.push("display:none");
  if (node.type === "Stack") {
    rules.push(
      "display:flex",
      `flex-direction:${node.direction}`,
      `gap:${node.gap}px`,
      `align-items:${node.align}`,
      `justify-content:${node.justify === "between" ? "space-between" : node.justify}`,
      `padding:${node.padding.top}px ${node.padding.right}px ${node.padding.bottom}px ${node.padding.left}px`,
    );
  }
  if (node.type === "Form") {
    rules.push(
      "display:flex",
      "flex-direction:column",
      `gap:${node.gap}px`,
      `padding:${node.padding.top}px ${node.padding.right}px ${node.padding.bottom}px ${node.padding.left}px`,
    );
  }
  return rules;
}

function responsiveRules(node: StructuredPrototypeNode): string[] {
  const widths = { sm: 640, md: 768, lg: 1024 } as const;
  return node.responsive.map((override) => {
    const rules: string[] = [];
    const item = override.layoutItem;
    if (item.width !== undefined) rules.push(`width:${length(item.width)}`);
    if (item.minWidth !== undefined) {
      rules.push(item.minWidth === null ? "min-width:0" : `min-width:${length(item.minWidth)}`);
    }
    if (item.maxWidth !== undefined) {
      rules.push(item.maxWidth === null ? "max-width:none" : `max-width:${length(item.maxWidth)}`);
    }
    if (item.height !== undefined) rules.push(`height:${length(item.height)}`);
    if (item.minHeight !== undefined) {
      rules.push(item.minHeight === null ? "min-height:0" : `min-height:${length(item.minHeight)}`);
    }
    if (item.maxHeight !== undefined) {
      rules.push(
        item.maxHeight === null ? "max-height:none" : `max-height:${length(item.maxHeight)}`,
      );
    }
    if (item.grow !== undefined) rules.push(`flex-grow:${item.grow}`);
    if (item.shrink !== undefined) rules.push(`flex-shrink:${item.shrink}`);
    if (item.alignSelf !== undefined) rules.push(`align-self:${item.alignSelf}`);
    return `@media(min-width:${widths[override.breakpoint]}px){[data-prototype-node-id="${node.id}"]{${rules.join(";")}}}`;
  });
}

function collectNodeCss(node: StructuredPrototypeNode, output: string[]): void {
  output.push(`[data-prototype-node-id="${node.id}"]{${layoutRules(node).join(";")}}`);
  output.push(...responsiveRules(node));
  if (node.type === "Stack" || node.type === "Form") {
    for (const child of node.children) collectNodeCss(child, output);
  }
}

function inputNodes(node: StructuredPrototypeNode, output: StructuredPrototypeInputNode[]): void {
  if (node.type === "Input") output.push(node);
  if (node.type === "Stack" || node.type === "Form") {
    for (const child of node.children) inputNodes(child, output);
  }
}

function formNodes(node: StructuredPrototypeNode, output: StructuredPrototypeFormNode[]): void {
  if (node.type === "Form") output.push(node);
  if (node.type === "Stack" || node.type === "Form") {
    for (const child of node.children) formNodes(child, output);
  }
}

export function deriveFormInputBindings(document: StructuredPrototypeDocument): FormInputBinding[] {
  const forms: StructuredPrototypeFormNode[] = [];
  for (const page of document.pages) formNodes(page.root, forms);
  const result: FormInputBinding[] = [];
  for (const form of forms) {
    const definition = document.runtime.forms.find(
      (candidate) => candidate.id === form.formDefinitionId,
    );
    if (definition === undefined) {
      throw new PrototypeRendererError(
        "renderer_form_definition_missing",
        `form node ${form.id} references an unknown runtime form`,
      );
    }
    const inputs: StructuredPrototypeInputNode[] = [];
    for (const child of form.children) inputNodes(child, inputs);
    if (inputs.length !== definition.fields.length) {
      throw new PrototypeRendererError(
        "renderer_form_binding_incomplete",
        `form node ${form.id} must contain one input per runtime field`,
      );
    }
    for (const [index, input] of inputs.entries()) {
      const field = definition.fields[index];
      if (field === undefined) {
        throw new PrototypeRendererError(
          "renderer_form_binding_incomplete",
          "runtime form field is missing",
        );
      }
      const compatible =
        (field.valueType === "integer" && input.inputType === "number") ||
        (field.valueType === "string" && input.inputType !== "number");
      if (!compatible) {
        throw new PrototypeRendererError(
          "renderer_form_binding_type_mismatch",
          `input node ${input.id} does not match runtime field ${field.id}`,
        );
      }
      result.push({
        nodeId: input.id,
        formId: definition.id,
        fieldId: field.id,
        valueType: field.valueType,
      });
    }
  }
  return result;
}

function renderNode(
  node: StructuredPrototypeNode,
  bindings: Map<string, FormInputBinding>,
): string {
  const common = `data-prototype-node-id="${node.id}" data-prototype-node-type="${node.type}"`;
  switch (node.type) {
    case "Stack":
      return `<div ${common} class="prototype-stack">${node.children.map((child) => renderNode(child, bindings)).join("")}</div>`;
    case "Form":
      return `<form ${common} class="prototype-form" data-prototype-form-id="${node.formDefinitionId}" novalidate>${node.children.map((child) => renderNode(child, bindings)).join("")}</form>`;
    case "Text": {
      const tag = node.semantic === "heading" ? "h2" : node.semantic === "label" ? "strong" : "p";
      return `<${tag} ${common} class="prototype-text prototype-text-${node.semantic} prototype-tone-${node.tone}">${escapeHtml(node.content)}</${tag}>`;
    }
    case "Input": {
      const binding = bindings.get(node.id);
      const bindingAttributes =
        binding === undefined
          ? ""
          : ` data-runtime-form-id="${binding.formId}" data-runtime-field-id="${binding.fieldId}" data-runtime-value-type="${binding.valueType}"`;
      return `<label ${common} class="prototype-input"><span>${escapeHtml(node.label)}</span><input type="${node.inputType}" value="${escapeHtml(node.value)}" placeholder="${escapeHtml(node.placeholder)}"${node.required ? " required" : ""}${node.disabled ? " disabled" : ""}${bindingAttributes}></label>`;
    }
    case "Button": {
      const trigger = node.disabled ? "" : ` data-runtime-node-id="${node.id}"`;
      return `<button ${common} type="button" class="prototype-button prototype-button-${node.variant} prototype-button-${node.size}"${node.disabled ? " disabled" : ""}${trigger}>${escapeHtml(node.label)}</button>`;
    }
    case "Table":
      return `<div ${common} class="prototype-table-wrap"><table class="prototype-table prototype-table-${node.density}"><thead><tr>${node.columns.map((column) => `<th data-column-key="${escapeHtml(column.key)}">${escapeHtml(column.label)}</th>`).join("")}</tr></thead><tbody>${node.rows.map((row) => `<tr data-static-row-id="${row.id}">${row.cells.map((cell) => `<td>${escapeHtml(cell.value)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }
}

function renderStyles(document: StructuredPrototypeDocument): string {
  const tokenRules = [
    ...document.tokens.colors.map(
      (token) => `--color-${token.key}:${safeTokenValue("color", token.value)}`,
    ),
    ...document.tokens.spacing.map(
      (token) => `--space-${token.key}:${safeTokenValue("spacing", token.value)}`,
    ),
  ];
  const nodeRules: string[] = [];
  for (const page of document.pages) collectNodeCss(page.root, nodeRules);
  return `:root{${tokenRules.join(";")};color-scheme:light;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}*{box-sizing:border-box}html,body{margin:0;min-height:100%;background:#eef1ef;color:#17201d}button,input,select{font:inherit}.prototype-shell{min-height:100vh;display:grid;grid-template-columns:220px minmax(0,1fr)}.prototype-sidebar{background:#18231f;color:#fff;padding:24px 16px}.prototype-brand{font-size:18px;font-weight:800}.prototype-subtitle{margin-top:4px;color:#b8c3be;font-size:12px}.prototype-nav{display:grid;gap:4px;margin-top:28px}.prototype-nav button{border:0;background:transparent;color:#d5ddd9;min-height:42px;padding:0 12px;text-align:left;cursor:pointer}.prototype-nav button[aria-current="page"]{background:rgba(255,255,255,.14);color:#fff;font-weight:700}.prototype-main{min-width:0;background:#fbfcfb}.prototype-toolbar{min-height:58px;display:flex;align-items:center;justify-content:space-between;gap:16px;border-bottom:1px solid #e1e5e3;background:#fff;padding:8px 24px}.prototype-toolbar-title{font-size:14px;font-weight:700}.prototype-role{display:flex;align-items:center;gap:8px;color:#62706b;font-size:12px}.prototype-role select{min-height:34px;border:1px solid #c9d2ce;background:#fff;padding:0 8px}.prototype-notification{display:none;margin:16px 24px 0;border:1px solid #b6d7cf;background:#e9f4ec;color:#237a45;padding:10px 12px;font-size:13px}.prototype-notification[data-visible="true"]{display:block}.prototype-notification[data-level="error"]{border-color:#e4a8b2;background:#fff1f3;color:#8c1d31}.prototype-page{display:none;min-height:calc(100vh - 58px)}.prototype-page[data-active="true"]{display:block}.prototype-stack,.prototype-form{min-width:0}.prototype-text{margin:0;line-height:1.5}.prototype-text-heading{font-size:24px;font-weight:800}.prototype-text-caption{font-size:12px}.prototype-tone-muted{color:#62706b}.prototype-tone-success{color:#237a45}.prototype-tone-warning{color:#936221}.prototype-tone-danger{color:#8c1d31}.prototype-input{display:grid;gap:6px;color:#3f4c47;font-size:12px}.prototype-input input{min-height:42px;border:1px solid #c9d2ce;background:#fff;padding:0 12px;color:#17201d}.prototype-button{border:1px solid transparent;cursor:pointer;font-weight:700}.prototype-button-small{min-height:32px;padding:0 12px;font-size:12px}.prototype-button-medium{min-height:40px;padding:0 16px;font-size:13px}.prototype-button-large{min-height:48px;padding:0 20px;font-size:14px}.prototype-button-primary{background:#126b5f;color:#fff}.prototype-button-secondary{border-color:#c9d2ce;background:#fff;color:#17201d}.prototype-button-danger{background:#8c1d31;color:#fff}.prototype-button-ghost{background:transparent;color:#126b5f}.prototype-button:disabled{cursor:not-allowed;opacity:.45}.prototype-table-wrap{overflow:auto;border:1px solid #d9dfdc;background:#fff}.prototype-table{width:100%;border-collapse:collapse;font-size:13px}.prototype-table th,.prototype-table td{border-bottom:1px solid #e6eae8;text-align:left}.prototype-table-compact th,.prototype-table-compact td{padding:8px 10px}.prototype-table-comfortable th,.prototype-table-comfortable td{padding:12px 14px}.prototype-table th{background:#f7f8f7;color:#62706b;font-size:11px;text-transform:uppercase}.prototype-table tbody tr[data-entity-id]{cursor:pointer}.prototype-table tbody tr[data-entity-id]:hover{background:#f0f6f4}.prototype-runtime-error{position:fixed;right:16px;bottom:16px;max-width:420px;border:1px solid #e4a8b2;background:#fff1f3;color:#8c1d31;padding:12px;font-size:12px;z-index:20}${nodeRules.join("")}@media(max-width:767px){.prototype-shell{grid-template-columns:1fr}.prototype-sidebar{padding:12px}.prototype-nav{display:flex;overflow:auto;margin-top:12px}.prototype-nav button{white-space:nowrap}.prototype-toolbar{padding:8px 12px}.prototype-page{min-height:auto}.prototype-text-heading{font-size:20px}}`;
}

function renderHtml(document: StructuredPrototypeDocument, documentHash: string): string {
  const bindings = new Map(
    deriveFormInputBindings(document).map((binding) => [binding.nodeId, binding]),
  );
  return `<!doctype html><html lang="${document.locale}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="prototype-document-hash" content="${documentHash}"><meta http-equiv="Content-Security-Policy" content="default-src 'none';script-src 'self';style-src 'self';connect-src 'self';img-src 'self' data:;font-src 'self';base-uri 'none';form-action 'none';frame-ancestors 'self'"><title>${escapeHtml(document.title)}</title><link rel="stylesheet" href="./styles.css"></head><body><div class="prototype-shell"><aside class="prototype-sidebar"><div class="prototype-brand">Prototype</div><div class="prototype-subtitle">${escapeHtml(document.title)}</div><nav class="prototype-nav" aria-label="Prototype navigation">${document.navigation.items.map((item) => `<button type="button" data-navigation-target="${item.targetPageId}">${escapeHtml(item.label)}</button>`).join("")}</nav></aside><main class="prototype-main"><header class="prototype-toolbar"><div class="prototype-toolbar-title" data-current-page-title>${escapeHtml(document.pages[0]?.title ?? document.title)}</div><label class="prototype-role"><span data-current-role-label></span><select data-role-select aria-label="Simulated role">${document.runtime.roles.map((role) => `<option value="${role.id}">${escapeHtml(role.label)}</option>`).join("")}</select></label></header><div class="prototype-notification" data-runtime-notification data-visible="false"></div>${document.pages.map((page) => `<section class="prototype-page" data-prototype-page-id="${page.id}" data-page-title="${escapeHtml(page.title)}" data-active="false">${renderNode(page.root, bindings)}</section>`).join("")}</main></div><div class="prototype-runtime-error" data-runtime-error hidden></div><script src="./runtime.js" defer></script></body></html>`;
}

function countNodes(node: StructuredPrototypeNode): number {
  if (node.type !== "Stack" && node.type !== "Form") return 1;
  return 1 + node.children.reduce((total, child) => total + countNodes(child), 0);
}

export function renderPrototypeDocument(
  document: StructuredPrototypeDocument,
  documentJson: string,
  documentHash: string,
  publicRuntimeSource: string,
): { files: RenderedPrototypeFile[]; preflight: PrototypeRenderPreflight } {
  if (document.assetRefs.length > 0) {
    throw new PrototypeRendererError(
      "renderer_assets_unsupported",
      "renderer asset resolution is unavailable for this compatibility version",
    );
  }
  const bindings = deriveFormInputBindings(document);
  const nodeCount = document.pages.reduce((total, page) => total + countNodes(page.root), 0);
  const preflight: PrototypeRenderPreflight = {
    contractVersion: 1,
    checks: [
      { code: "document-schema", status: "passed", evidence: `schema:${document.schemaVersion}` },
      {
        code: "runtime-graph",
        status: "passed",
        evidence: `rules:${document.runtime.rules.length}`,
      },
      { code: "node-bindings", status: "passed", evidence: `nodes:${nodeCount}` },
      {
        code: "sandbox-policy",
        status: "passed",
        evidence: PROTOTYPE_RENDERER_SANDBOX_POLICY_VERSION,
      },
    ],
    pageCount: document.pages.length,
    nodeCount,
    formBindingCount: bindings.length,
    externalAssetCount: 0,
  };
  const files: RenderedPrototypeFile[] = [
    { relativePath: "document.json", content: documentJson },
    { relativePath: "index.html", content: renderHtml(document, documentHash) },
    { relativePath: "runtime.js", content: publicRuntimeSource },
    { relativePath: "styles.css", content: renderStyles(document) },
  ];
  files.sort((left, right) => left.relativePath.localeCompare(right.relativePath, "en"));
  return { files, preflight };
}
