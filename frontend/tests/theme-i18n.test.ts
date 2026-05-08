import test from "node:test";
import assert from "node:assert/strict";

import { DEFAULT_LOCALE, getDictionaryValue, isLocale } from "../src/lib/i18n";

test("locale validation accepts supported locales only", () => {
  assert.equal(isLocale("zh-CN"), true);
  assert.equal(isLocale("en-US"), true);
  assert.equal(isLocale("fr-FR"), false);
});

test("dictionary defaults to Chinese copy", () => {
  assert.equal(DEFAULT_LOCALE, "zh-CN");
  assert.equal(getDictionaryValue("zh-CN", "nav.home"), "首页");
  assert.equal(getDictionaryValue("en-US", "nav.home"), "Home");
});
