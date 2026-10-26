import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    rules: {
      // crypto.randomUUID is undefined over plain HTTP (insecure context): use the fallback helper.
      "no-restricted-properties": [
        "error",
        {
          object: "crypto",
          property: "randomUUID",
          message: 'Use randomUUID() from "@/lib/uuid" (works over plain HTTP too).',
        },
      ],
    },
  },
  {
    files: ["lib/uuid.ts"],
    rules: { "no-restricted-properties": "off" },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
