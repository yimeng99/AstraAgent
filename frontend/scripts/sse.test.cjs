const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const ts = require("typescript");
const source = fs.readFileSync(require.resolve("../src/utils/sse.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText;
const context = { exports: {}, TextDecoder };
vm.runInNewContext(compiled, context);
const { consumeSse } = context.exports;
test("SSE handles byte fragmentation, unicode, CRLF and multiline data", async () => {
  const bytes = new TextEncoder().encode(
    'data: {"type":"message.delta",\r\ndata: "delta":"中文\\n下一行"}\r\n\r\n: heartbeat\n\ndata: {"type":"artifact.created","artifact":{"file_id":"f"}}\n\n',
  );
  const stream = new ReadableStream({
    start(controller) {
      for (const byte of bytes) controller.enqueue(Uint8Array.of(byte));
      controller.close();
    },
  });
  const events = [];
  await consumeSse(stream, (event) => events.push(event));
  assert.equal(events.length, 2);
  assert.equal(events[0].delta, "中文\n下一行");
  assert.equal(events[1].artifact.file_id, "f");
  assert.equal(stream.locked, false);
});
test("SSE preserves server errors and ignores heartbeat or invalid JSON", async () => {
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(
        new TextEncoder().encode(
          ': heartbeat\n\ndata: invalid\n\ndata: {"type":"error","error":"failed"}\n\n',
        ),
      );
      controller.close();
    },
  });
  const events = [];
  await consumeSse(stream, (event) => events.push(event));
  assert.equal(events.length, 1);
  assert.equal(events[0].error, "failed");
});
