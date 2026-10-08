const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const ts = require("typescript");

const compiled = ts.transpileModule(
  fs.readFileSync(require.resolve("../src/utils/executionFailure.ts"), "utf8"),
  { compilerOptions: { module: ts.ModuleKind.CommonJS } },
).outputText;
const context = { exports: {} };
vm.runInNewContext(compiled, context);
const { failureMessage, failureTime } = context.exports;

test("cancellation records identify shutdown, lease loss, and a user stop", () => {
  const failure = { error_type: "CancelledError", stage: "tool", message: "任务执行中断" };
  assert.equal(
    failureMessage({ ...failure, reason: "server_shutdown" }),
    "服务重启或关闭导致执行中断",
  );
  assert.equal(failureMessage({ ...failure, reason: "lease_lost" }), "执行连接中断");
  assert.equal(failureMessage({ ...failure, reason: "user_stop" }), "已停止");
  assert.equal(failureMessage({ ...failure, reason: "execution_error" }), "任务执行中断");
});

test("separate interruption times stay visible to the second", () => {
  const first = failureTime("2026-10-07T10:05:26Z");
  const second = failureTime("2026-10-07T10:06:29Z");
  assert.match(first, /2026.*10.*07/);
  assert.match(first, /05:26/);
  assert.match(second, /06:29/);
  assert.notEqual(first, second);
});
