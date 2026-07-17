import test from "node:test";
import assert from "node:assert/strict";

import { DEFAULT_LOCALE, dictionaries, getDictionaryValue, isLocale } from "../src/lib/i18n";

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

test("runtime dictionaries do not expose generated placeholder copy", () => {
  for (const [locale, dictionary] of Object.entries(dictionaries)) {
    for (const [key, value] of Object.entries(dictionary)) {
      assert.doesNotMatch(
        value,
        /^(?:TODO\b|（待补充）)/,
        `${locale}.${key} still exposes generated placeholder copy`,
      );
    }
  }
});

test("runtime dictionaries expose the same translation keys in both locales", () => {
  const zhKeys = Object.keys(dictionaries["zh-CN"]).sort();
  const enKeys = Object.keys(dictionaries["en-US"]).sort();

  assert.deepEqual(enKeys, zhKeys);
});

test("structured prototype form feedback is domain neutral in both locales", () => {
  const values = [
    getDictionaryValue("zh-CN", "prototype.structured.form.selectionRequired"),
    getDictionaryValue("zh-CN", "prototype.structured.form.invalid"),
    getDictionaryValue("en-US", "prototype.structured.form.selectionRequired"),
    getDictionaryValue("en-US", "prototype.structured.form.invalid"),
  ];

  assert.deepEqual(values, [
    "请先选择要插入的表单",
    "请检查表单中的必填项和字段格式",
    "Select a form before inserting it",
    "Review the required fields and field formats",
  ]);
  for (const value of values) {
    assert.doesNotMatch(value, /申请事项|金额|request title|amount/iu);
  }
});
