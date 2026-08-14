import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

// Severities are left exactly as eslint-config-next ships them. What makes the
// warn-level rules — the six `jsx-a11y/*` among them — actually block is
// `--max-warnings 0` on the `lint` script in package.json. Promoting rules here
// instead would have to be done one at a time and would silently miss whatever
// next adds next.
const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Committed third-party build artifact — the self-contained System Card
    // Vite bundle. It ships minified and is not ours to lint.
    "public/system-card/**",
    // Playwright's own generated output. Both are gitignored, so CI never
    // sees them: Frontend CI lints a tree that has never run the suite. Run
    // Playwright once locally and `pnpm lint` then reports ~3000 problems
    // from a minified report bundle and exits 1 — a break that exists only
    // on a developer's machine, which is the same "passes because of where
    // it runs" shape as the session skips this branch is about (#188).
    "playwright-report/**",
    "test-results/**",
  ]),
]);

export default eslintConfig;
