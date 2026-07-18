import type { CSSProperties } from "react";

import { resolvePrototypeShellTheme } from "./prototypeRendererCore";
import type { StructuredPrototypeDocument } from "./types";

export function resolveStructuredPrototypeTheme(
  document: StructuredPrototypeDocument,
): CSSProperties & Record<`--prototype-${string}`, string> {
  const theme = resolvePrototypeShellTheme(document);
  const style: CSSProperties & Record<`--prototype-${string}`, string> = {
    colorScheme: document.settings.theme === "system" ? "light dark" : document.settings.theme,
    "--prototype-accent": theme.accent,
    "--prototype-accent-text": theme.accentText,
    "--prototype-navigation-background": theme.navigationBackground,
    "--prototype-navigation-text": theme.navigationText,
    "--prototype-content-background": theme.contentBackground,
    "--prototype-content-text": theme.contentText,
    "--prototype-surface": theme.surface,
    "--prototype-surface-text": theme.surfaceText,
    "--prototype-text": "var(--prototype-content-text)",
  };
  document.tokens.colors.forEach((token, index) => {
    style[`--prototype-color-${index}`] = token.value;
  });
  document.tokens.spacing.forEach((token, index) => {
    style[`--prototype-space-${index}`] = token.value;
  });
  return style;
}
