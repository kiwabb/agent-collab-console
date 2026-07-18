const BASE_PROTOTYPE_CUSTOM_PROPERTIES = [
  "--prototype-accent",
  "--prototype-accent-text",
  "--prototype-navigation-background",
  "--prototype-navigation-text",
  "--prototype-content-background",
  "--prototype-content-text",
  "--prototype-surface",
  "--prototype-surface-text",
  "--prototype-text",
] as const;

const MIRROR_IDENTITY_ATTRIBUTES = [
  "id",
  "for",
  "name",
  "aria-controls",
  "aria-describedby",
  "aria-labelledby",
  "aria-owns",
  "data-node-id",
  "data-container-id",
  "data-prototype-active-layout-node-id",
  "data-prototype-measured-layout-child-count",
  "data-prototype-drop-area-count",
] as const;

export interface StructuredPrototypeDragMirrorGeometry {
  clientWidth: number;
  clientHeight: number;
  contentWidth: number;
  contentHeight: number;
  scaleX: number;
  scaleY: number;
}

export interface StructuredPrototypeDragMirrorSnapshot {
  element: HTMLElement;
  geometry: StructuredPrototypeDragMirrorGeometry;
  scrollStates: readonly StructuredPrototypeDragMirrorScrollState[];
  customProperties: Readonly<Record<string, string>>;
  fontFamily: string;
  colorScheme: string;
}

export interface StructuredPrototypeDragMirrorScrollState {
  element: HTMLElement;
  scrollLeft: number;
  scrollTop: number;
}

export interface StructuredPrototypeDragMirrorRootStyle {
  position: "relative";
  inset: "auto";
  top: "auto";
  right: "auto";
  bottom: "auto";
  left: "auto";
  width: string;
  height: string;
  minWidth: "0px";
  minHeight: "0px";
  maxWidth: "none";
  maxHeight: "none";
  margin: "0px";
  boxSizing: "border-box";
  flex: "0 0 auto";
  alignSelf: "auto";
  justifySelf: "auto";
  gridArea: "auto";
  order: "0";
  transform: "none";
  translate: "none";
  rotate: "none";
  scale: "none";
  transition: "none";
}

function isPositiveFinite(value: number): boolean {
  return Number.isFinite(value) && value > 0;
}

export function resolveStructuredPrototypeDragMirrorGeometry({
  clientWidth,
  clientHeight,
  contentWidth,
  contentHeight,
}: {
  clientWidth: number;
  clientHeight: number;
  contentWidth: number;
  contentHeight: number;
}): StructuredPrototypeDragMirrorGeometry | null {
  if (
    !isPositiveFinite(clientWidth) ||
    !isPositiveFinite(clientHeight) ||
    !isPositiveFinite(contentWidth) ||
    !isPositiveFinite(contentHeight)
  ) {
    return null;
  }
  return {
    clientWidth,
    clientHeight,
    contentWidth,
    contentHeight,
    scaleX: clientWidth / contentWidth,
    scaleY: clientHeight / contentHeight,
  };
}

function collectPrototypeCustomProperties(style: CSSStyleDeclaration): Record<string, string> {
  const properties: Record<string, string> = {};
  const names = new Set<string>(BASE_PROTOTYPE_CUSTOM_PROPERTIES);
  for (let index = 0; index < style.length; index += 1) {
    const name = style.item(index);
    if (name.startsWith("--prototype-")) names.add(name);
  }
  for (const name of names) {
    const value = style.getPropertyValue(name).trim();
    if (value !== "") properties[name] = value;
  }
  return properties;
}

export function resolveStructuredPrototypeDragMirrorRootStyle(
  contentWidth: number,
  contentHeight: number,
): StructuredPrototypeDragMirrorRootStyle | null {
  if (!isPositiveFinite(contentWidth) || !isPositiveFinite(contentHeight)) return null;
  return {
    position: "relative",
    inset: "auto",
    top: "auto",
    right: "auto",
    bottom: "auto",
    left: "auto",
    width: `${contentWidth}px`,
    height: `${contentHeight}px`,
    minWidth: "0px",
    minHeight: "0px",
    maxWidth: "none",
    maxHeight: "none",
    margin: "0px",
    boxSizing: "border-box",
    flex: "0 0 auto",
    alignSelf: "auto",
    justifySelf: "auto",
    gridArea: "auto",
    order: "0",
    transform: "none",
    translate: "none",
    rotate: "none",
    scale: "none",
    transition: "none",
  };
}

function copyMirrorLiveState(
  source: HTMLElement,
  clone: HTMLElement,
): readonly StructuredPrototypeDragMirrorScrollState[] | null {
  const sourceElements: Element[] = [source, ...source.querySelectorAll("*")];
  const cloneElements: Element[] = [clone, ...clone.querySelectorAll("*")];
  if (sourceElements.length !== cloneElements.length) return null;

  const scrollStates: StructuredPrototypeDragMirrorScrollState[] = [];
  for (let index = 0; index < sourceElements.length; index += 1) {
    const sourceElement = sourceElements[index];
    const cloneElement = cloneElements[index];
    if (sourceElement === undefined || cloneElement === undefined) return null;

    if (sourceElement instanceof HTMLInputElement) {
      if (!(cloneElement instanceof HTMLInputElement)) return null;
      cloneElement.value = sourceElement.value;
      cloneElement.checked = sourceElement.checked;
      cloneElement.indeterminate = sourceElement.indeterminate;
    } else if (sourceElement instanceof HTMLTextAreaElement) {
      if (!(cloneElement instanceof HTMLTextAreaElement)) return null;
      cloneElement.textContent = sourceElement.value;
      cloneElement.value = sourceElement.value;
    } else if (sourceElement instanceof HTMLSelectElement) {
      if (!(cloneElement instanceof HTMLSelectElement)) return null;
      const sourceOptions = [...sourceElement.options];
      const cloneOptions = [...cloneElement.options];
      if (sourceOptions.length !== cloneOptions.length) return null;
      for (let optionIndex = 0; optionIndex < sourceOptions.length; optionIndex += 1) {
        const sourceOption = sourceOptions[optionIndex];
        const cloneOption = cloneOptions[optionIndex];
        if (sourceOption === undefined || cloneOption === undefined) return null;
        cloneOption.selected = sourceOption.selected;
      }
    }

    if (sourceElement instanceof HTMLElement && cloneElement instanceof HTMLElement) {
      scrollStates.push({
        element: cloneElement,
        scrollLeft: sourceElement.scrollLeft,
        scrollTop: sourceElement.scrollTop,
      });
    }
  }
  return scrollStates;
}

export function restoreStructuredPrototypeDragMirrorScrollState(
  scrollStates: readonly StructuredPrototypeDragMirrorScrollState[],
): void {
  for (const state of scrollStates) {
    state.element.scrollLeft = state.scrollLeft;
    state.element.scrollTop = state.scrollTop;
  }
}

function sanitizeMirrorElement(
  element: HTMLElement,
  rootStyle: StructuredPrototypeDragMirrorRootStyle,
): void {
  for (const dropTarget of element.querySelectorAll<HTMLElement>("[data-prototype-drop-intent]")) {
    dropTarget.remove();
  }
  const descendants = [element, ...element.querySelectorAll<HTMLElement>("*")];
  for (const descendant of descendants) {
    for (const attribute of MIRROR_IDENTITY_ATTRIBUTES) descendant.removeAttribute(attribute);
    descendant.removeAttribute("autofocus");
    descendant.removeAttribute("contenteditable");
    descendant.setAttribute("tabindex", "-1");
  }
  element.setAttribute("aria-hidden", "true");
  element.setAttribute("inert", "");
  element.style.pointerEvents = "none";
  element.style.opacity = "1";
  Object.assign(element.style, rootStyle);
}

export function captureStructuredPrototypeDragMirror(
  source: HTMLElement,
): StructuredPrototypeDragMirrorSnapshot | null {
  const bounds = source.getBoundingClientRect();
  const geometry = resolveStructuredPrototypeDragMirrorGeometry({
    clientWidth: bounds.width,
    clientHeight: bounds.height,
    contentWidth: source.offsetWidth,
    contentHeight: source.offsetHeight,
  });
  if (geometry === null) return null;
  const rootStyle = resolveStructuredPrototypeDragMirrorRootStyle(
    geometry.contentWidth,
    geometry.contentHeight,
  );
  if (rootStyle === null) return null;

  const clonedNode = source.cloneNode(true);
  if (!(clonedNode instanceof HTMLElement)) return null;
  const scrollStates = copyMirrorLiveState(source, clonedNode);
  if (scrollStates === null) return null;
  sanitizeMirrorElement(clonedNode, rootStyle);
  const computedStyle = window.getComputedStyle(source);
  return {
    element: clonedNode,
    geometry,
    scrollStates,
    customProperties: collectPrototypeCustomProperties(computedStyle),
    fontFamily: computedStyle.fontFamily,
    colorScheme: computedStyle.colorScheme,
  };
}

export type StructuredPrototypeDragMirrorCapture =
  () => StructuredPrototypeDragMirrorSnapshot | null;
