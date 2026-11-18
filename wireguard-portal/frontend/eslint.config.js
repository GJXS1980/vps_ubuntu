import ts from "typescript-eslint";
import vue from "eslint-plugin-vue";
export default [
  ...vue.configs["flat/essential"],
  {
    files: ["**/*.vue"],
    languageOptions: { parserOptions: { parser: ts.parser } },
  },
  { files: ["**/*.ts"], languageOptions: { parser: ts.parser } },
];
