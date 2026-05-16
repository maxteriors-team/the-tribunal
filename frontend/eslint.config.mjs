import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import eslintConfigPrettier from "eslint-config-prettier";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    rules: {
      "no-console": ["error", { allow: ["warn", "error"] }],
      // Require an accessible label on interactive controls. Icon-only buttons
      // must supply `aria-label` (or wrap a labelled child like an <a aria-label>)
      // so screen readers can announce them.
      "jsx-a11y/control-has-associated-label": [
        "error",
        {
          labelAttributes: ["aria-label", "aria-labelledby", "title"],
          controlComponents: ["Button"],
          ignoreElements: [
            "audio",
            "canvas",
            "embed",
            "input",
            "textarea",
            "tr",
            "video",
          ],
          ignoreRoles: [
            "grid",
            "listbox",
            "menu",
            "menubar",
            "radiogroup",
            "row",
            "tablist",
            "toolbar",
            "tree",
            "treegrid",
          ],
          depth: 5,
        },
      ],
      // Forbid inline string-tuple React Query keys. All query keys must be
      // produced by `queryKeys.<resource>.<scope>(...)` from `@/lib/query-keys`
      // so that invalidation, prefetch, and cache reads share one source of truth.
      "no-restricted-syntax": [
        "error",
        {
          selector:
            "Property[key.name='queryKey'] > ArrayExpression",
          message:
            "Inline `queryKey: [...]` literals are not allowed. Use `queryKeys.<resource>.<scope>(...)` from '@/lib/query-keys' instead. Add a new builder there if needed.",
        },
      ],
      "no-restricted-imports": [
        "error",
        {
          paths: [
            {
              name: "date-fns",
              message:
                "Import date helpers from '@/lib/utils/date' instead. The date.ts wrapper is the only file allowed to depend on date-fns directly.",
            },
          ],
          patterns: [
            {
              group: ["date-fns/*"],
              message:
                "Import date helpers from '@/lib/utils/date' instead of date-fns submodules.",
            },
          ],
        },
      ],
    },
  },
  {
    files: ["src/lib/utils/date.ts"],
    rules: {
      "no-restricted-imports": "off",
    },
  },
  {
    // The factory file itself is the canonical source of literal query keys.
    files: ["src/lib/query-keys.ts"],
    rules: {
      "no-restricted-syntax": "off",
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
  // Must come last: disables ESLint rules that conflict with Prettier formatting.
  eslintConfigPrettier,
]);

export default eslintConfig;
