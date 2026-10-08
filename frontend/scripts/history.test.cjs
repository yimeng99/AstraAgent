const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const ts = require("typescript");
const source = fs.readFileSync(require.resolve("../src/utils/history.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText;
const context = { exports: {} };
vm.runInNewContext(compiled, context);
const { toChatMessages } = context.exports;
test("tool phases retain assistant boundaries without changing stored history", () => {
  const history = [
    {
      id: "u",
      role: "user",
      content: "question",
      attachments: [{ file_id: "f", filename: "a.pdf" }],
    },
    { id: "a", role: "assistant", content: "", reasoning: "first" },
    { role: "tool", content: "result" },
    { id: "b", role: "assistant", content: "answer", reasoning: "second" },
  ];
  const before = JSON.stringify(history);
  const result = toChatMessages(history, "thread");
  assert.equal(result.length, 3);
  assert.equal(result[2].content, "answer");
  assert.equal(result[1].reasoning, "first");
  assert.equal(result[2].reasoning, "second");
  assert.equal(result[0].attachments[0].fileId, "f");
  assert.equal(JSON.stringify(history), before);
});
test("separate user turns remain separate replies", () => {
  const result = toChatMessages(
    [
      { role: "user", content: "one" },
      { role: "assistant", content: "first" },
      { role: "user", content: "two" },
      { role: "assistant", content: "second" },
    ],
    "thread",
  );
  assert.equal(result.length, 4);
  assert.equal(result[3].content, "second");
});
