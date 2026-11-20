// Project lint: one entry per defect a rule can catch again. Each restricted import names where
// it came from and, in its message, the public interface to use instead, so the error is the fix.
import { defineConfig } from "eslint/config";
import tseslint from "typescript-eslint";

/** Cross-layer import boundaries. `group` entries are gitignore-style globs over the import specifier. */
export const RESTRICTED_IMPORTS = [
  {
    origin: "V1812-OPENAPI-TYPES: 66 hand-written response types drifted from the server; every client type now comes from the generated schema through apiTypes",
    owner: "src/apiTypes.ts",
    patterns: [{
      group: ["**/generated/api-schema", "**/generated/api-schema.js", "**/generated/api-schema.ts"],
      message: "Import Schema / ResponseOf from src/apiTypes.ts (or a named alias exported there); only apiTypes.ts reads the generated OpenAPI schema.",
    }],
  },
  {
    origin: "Workbench HTTP API: giving UI modules a direct import of a transport implementation splits the API entry point; src/api.ts already exports the graph and export clients",
    owner: "src/api.ts",
    patterns: [{
      group: [
        "**/apiGraph", "**/apiGraph.js", "**/apiGraph.ts",
        "**/apiExports", "**/apiExports.js", "**/apiExports.ts",
      ],
      message: "Import the graph or export client from src/api.ts, the public Workbench HTTP API.",
    }],
  },
];

/** The same glob as an esquery regex, for the forms no-restricted-imports does not see. */
function specifierRegex(glob) {
  const body = glob.split("**/").map((part) => part.replace(/[.+?^${}()|[\]\\/]/g, "\\$&").replace(/\*/g, "[^/]*"));
  return `/(^|\\/)${body.filter(Boolean).join("(.*\\/)?")}$/`;
}

function boundaryRules(patterns) {
  const syntax = patterns.flatMap(({ group, message }) => group.flatMap((glob) => {
    const regex = specifierRegex(glob);
    return [
      { selector: `ImportExpression[source.value=${regex}]`, message },
      { selector: `ImportExpression[source.expressions.length=0][source.quasis.0.value.cooked=${regex}]`, message },
      { selector: `TSImportType[source.value=${regex}]`, message },
    ];
  }));
  return {
    "@typescript-eslint/no-restricted-imports": ["error", { patterns }],
    "no-restricted-syntax": ["error", ...syntax],
  };
}

// ESLint replaces a rule's options in a later matching config. Publish one
// combined list per owner so opening that owner's boundary keeps the others.
const boundaryOwners = [...new Set(RESTRICTED_IMPORTS.map(({ owner }) => owner))];
const importBoundaryConfigs = [
  {
    files: ["src/**/*.{ts,tsx}"],
    ignores: ["src/**/*.test.{ts,tsx}", ...boundaryOwners],
    rules: boundaryRules(RESTRICTED_IMPORTS.flatMap(({ patterns }) => patterns)),
  },
  ...boundaryOwners.map((file) => ({
    files: [file],
    rules: boundaryRules(RESTRICTED_IMPORTS.flatMap(({ owner, patterns }) => owner === file ? [] : patterns)),
  })),
];

export default defineConfig(
  { ignores: ["dist/**", "node_modules/**", "src/generated/**"] },
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: { parser: tseslint.parser, parserOptions: { ecmaFeatures: { jsx: true } } },
    plugins: { "@typescript-eslint": tseslint.plugin },
    // Inline disable comments have no effect, so a boundary is never waived line by line.
    linterOptions: { noInlineConfig: true, reportUnusedDisableDirectives: "off" },
  },
  ...importBoundaryConfigs,
);
