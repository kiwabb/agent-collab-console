// Phase 4 refactor: split the 3606-line monolithic i18n.ts into per-locale
// files. The public API (LOCALES, DEFAULT_LOCALE, Locale, TranslationKey,
// dictionaries, isLocale, getDictionaryValue) is preserved so call sites
// do not change.

import zhCN from "./zh-CN";
import enUS from "./en-US";

export const LOCALES = ["zh-CN", "en-US"] as const;
export type Locale = (typeof LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "zh-CN";

export const dictionaries = {
  "zh-CN": zhCN,
  "en-US": enUS,
};

export type TranslationKey = keyof (typeof dictionaries)["zh-CN"];

export function isLocale(value: string | null | undefined): value is Locale {
  return value === "zh-CN" || value === "en-US";
}

export function getDictionaryValue(locale: Locale, key: TranslationKey): string {
  return (
    (dictionaries[locale] as Record<string, string>)[key] ??
    (dictionaries[DEFAULT_LOCALE] as Record<string, string>)[key] ??
    key
  );
}
