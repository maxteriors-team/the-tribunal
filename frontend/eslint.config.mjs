import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import eslintConfigPrettier from "eslint-config-prettier";
import jsxA11y from "eslint-plugin-jsx-a11y";
import unusedImports from "eslint-plugin-unused-imports";

// `eslint-config-next` already registers the `import` and `jsx-a11y` plugins.
// Re-registering them in a flat config errors with "Cannot redefine plugin",
// so we only register plugins it doesn't ship (unused-imports) and merge the
// recommended jsx-a11y rules in directly.
const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    plugins: {
      "unused-imports": unusedImports,
    },
    rules: {
      ...jsxA11y.flatConfigs.recommended.rules,
    },
  },
  {
    settings: {
      // Help eslint-plugin-import resolve TS path aliases (e.g. "@/...").
      "import/resolver": {
        typescript: {
          alwaysTryTypes: true,
          project: "./tsconfig.json",
        },
        node: true,
      },
    },
    rules: {
      // Project rules

      "no-console": ["warn", { allow: ["warn", "error"] }],
      "@typescript-eslint/no-explicit-any": "error",
      "@next/next/no-img-element": "error",
      "@next/next/no-html-link-for-pages": "error",

      // Drop unused imports automatically (autofixable).
      "unused-imports/no-unused-imports": "error",

      // Enforce a consistent, alphabetized import order grouped by origin.
      "import/order": [
        "error",
        {
          groups: [
            "builtin",
            "external",
            "internal",
            "parent",
            "sibling",
            "index",
          ],
          "newlines-between": "always",
          alphabetize: { order: "asc", caseInsensitive: true },
          pathGroups: [
            { pattern: "@/**", group: "internal", position: "before" },
          ],
          pathGroupsExcludedImportTypes: ["builtin"],
        },
      ],

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
          selector: "Property[key.name='queryKey'] > ArrayExpression",
          message:
            "Inline `queryKey: [...]` literals are not allowed. Use `queryKeys.<resource>.<scope>(...)` from '@/lib/query-keys' instead. Add a new builder there if needed.",
        },
        {
          selector:
            "ImportDeclaration[source.value='react'] > ImportNamespaceSpecifier",
          message:
            "Use named imports from 'react' (e.g. `import { useState, type ReactNode } from 'react'`) instead of `import * as React from 'react'`. React 19 + the new JSX transform make the namespace import unnecessary.",
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
  {
    // shadcn/ui primitives are vendored from upstream and follow shadcn's
    // `import * as React` convention. Keep them on the upstream style so future
    // `npx shadcn add` runs don't fight our lint rule.
    files: ["src/components/ui/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector: "Property[key.name='queryKey'] > ArrayExpression",
          message:
            "Inline `queryKey: [...]` literals are not allowed. Use `queryKeys.<resource>.<scope>(...)` from '@/lib/query-keys' instead. Add a new builder there if needed.",
        },
      ],
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Auto-generated by `npm run codegen` from backend/openapi.json.
    "src/lib/api/_generated.ts",
  ]),
  // Must come last: disables ESLint rules that conflict with Prettier formatting.
  eslintConfigPrettier,
]);

export default eslintConfig;
