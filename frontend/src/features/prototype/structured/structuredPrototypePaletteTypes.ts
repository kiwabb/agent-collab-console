export const STRUCTURED_PROTOTYPE_PALETTE_TYPES = [
  "Freeform",
  "Stack",
  "Grid",
  "Form",
  "Text",
  "Input",
  "Button",
  "Table",
] as const;

export type StructuredPrototypePaletteType = (typeof STRUCTURED_PROTOTYPE_PALETTE_TYPES)[number];
