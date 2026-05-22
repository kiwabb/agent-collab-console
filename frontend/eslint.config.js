import nextCoreWebVitals from "eslint-config-next/core-web-vitals";

const eslintConfig = [
  ...nextCoreWebVitals,
  {
    rules: {
      "react-hooks/exhaustive-deps": "warn",
      "react-hooks/set-state-in-effect": "off",
      "react-hooks/refs": "off",
      "react-hooks/purity": "off",
      "react-hooks/incompatible-library": "warn",
      "react-hooks/preserve-manual-memoization": "off",
      "react/no-unescaped-entities": "warn",
    },
  },
];

export default eslintConfig;
