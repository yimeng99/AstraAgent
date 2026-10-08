const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const ts = require("typescript");
const context = { exports: {} };
vm.runInNewContext(
  ts.transpileModule(fs.readFileSync(require.resolve("../src/utils/toolTodos.ts"), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS },
  }).outputText,
  context,
);
const parse = (value) => JSON.parse(JSON.stringify(context.exports.parseToolTodos(value)));

test("reads JSON todo lists and preserves text", () => {
  const todos = [{ content: '第一章 [背景] "说明"\n下一行', status: "in_progress" }];
  assert.deepEqual(parse(JSON.stringify({ todos })), todos);
  assert.deepEqual(parse(JSON.stringify(todos)), todos);
});
test("reads Python Command todos once, including escaped quotes", () => {
  const source = String.raw`Command(update={'todos': [{'content': '用户\'s [计划]', 'status': 'pending'}, {'content': "完成", 'status': 'completed'}], 'messages': [ToolMessage(content="Updated todo list to [{'content': '重复', 'status': 'pending'}]")]})`;
  assert.deepEqual(parse(source), [
    { content: "用户's [计划]", status: "pending" },
    { content: "完成", status: "completed" },
  ]);
});
test("invalid or truncated results safely fall back without executing text", () => {
  assert.deepEqual(parse("Command(update={'todos': [{'content': '未完成"), []);
  assert.deepEqual(parse("工具失败"), []);
  assert.deepEqual(parse('{"todos": [null, {"content":"未知", "status":"invalid"}]}'), []);
});
