import js from "@eslint/js";
import vue from "eslint-plugin-vue";
import vueParser from "vue-eslint-parser";
import tseslint from "typescript-eslint";
import globals from "globals";
import prettier from "eslint-config-prettier";

export default tseslint.config(
  { ignores: ["dist/**", "node_modules/**", "coverage/**", "**/*.tsbuildinfo"] },
  js.configs.recommended,
  ...tseslint.configs.recommended.map((config) => ({
    ...config,
    files: ["**/*.{ts,vue}"],
  })),
  ...vue.configs["flat/recommended"],
  { files: ["src/**/*.{ts,vue}"], languageOptions: { globals: globals.browser } },
  {
    files: ["**/*.vue"],
    languageOptions: { parser: vueParser, parserOptions: { parser: tseslint.parser } },
    // App、Markdown 等现有组件名保持稳定，避免无关的文件改名。
    rules: { "vue/multi-word-component-names": "off" },
  },
  { files: ["*.js", "*.ts", "scripts/**/*.cjs"], languageOptions: { globals: globals.node } },
  prettier,
);
