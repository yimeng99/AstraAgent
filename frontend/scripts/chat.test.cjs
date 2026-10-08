const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");
const { createPinia, setActivePinia, disposePinia } = require("pinia");
require.extensions[".ts"] = (module, filename) => {
  const code = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  module._compile(
    code.replace(/require\("((?:\.{1,2}\/|@\/)[^".]+)"\)/g, (_, target) => {
      if (target.startsWith("@/")) target = path.resolve(__dirname, "../src", target.slice(2));
      const resolved = fs.existsSync(path.resolve(path.dirname(filename), `${target}.ts`))
        ? `${target}.ts`
        : `${target}/index.ts`;
      return `require(${JSON.stringify(resolved)})`;
    }),
    filename,
  );
};
const { useChatStore } = require("../src/stores/chat.ts");
const { useUserStore } = require("../src/stores/user.ts");
const { http } = require("../src/utils/request/http.ts");

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

test("user list selects the first API user and only switches to active users", async () => {
  const app = mount();
  try {
    const users = [
      { user_id: "u-first", name: "张三", active: true },
      { user_id: "u-second", name: "李四", active: true },
      { user_id: "u-disabled", name: "王五", active: false },
    ];
    app.intercept((config) => (config.url === "/user/getMockUserList" ? users : undefined));
    const user = useUserStore();
    await user.loadUsers();
    assert.equal(user.userId, "u-first");
    assert.equal(user.mockUserList.length, 3);
    assert.equal(app.calls[0].baseURL, "/");
    user.selectUser("u-second");
    assert.equal(user.userId, "u-second");
    user.selectUser("u-disabled");
    assert.equal(user.userId, "u-second");
  } finally {
    app.close();
  }
});
function stream(events) {
  return new Response(
    [{ type: "message.start" }, ...events]
      .map((event) => `data: ${JSON.stringify(event)}\n\n`)
      .join(""),
  );
}

test("metrics events update session counters without adding message content", async () => {
  const env = mount();
  try {
    const metrics = { model_calls: 2, tool_calls: 1, steps: 5, total_tokens: 120, tps: 10 };
    global.fetch = async () => stream([{ type: "metrics", metrics }, { type: "done" }]);
    env.chat.draft = "统计测试";
    await env.chat.send();
    assert.deepEqual({ ...env.chat.metrics }, metrics);
    assert.ok(!env.chat.messages.some((message) => message.content.includes("model_calls")));
    env.chat.newThread();
    assert.equal(env.chat.metrics, null);
  } finally {
    env.close();
  }
});
function mount() {
  const pinia = createPinia();
  setActivePinia(pinia);
  useUserStore().currentUser = { user_id: "u-1001", name: "测试用户", active: true };
  const calls = [];
  const originalAdapter = http.defaults.adapter,
    originalFetch = global.fetch;
  const originalStorage = global.localStorage;
  const values = new Map();
  global.localStorage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
  const history = [
    { id: "u-1001-one", title: "one" },
    { id: "u-1001-two", title: "two" },
  ];
  let interactions = { approvals: [], questions: [] };
  let storedMessages;
  let intercept;
  http.defaults.adapter = async (config) => {
    calls.push(config);
    const extra = await intercept?.(config);
    let data = extra;
    if (data === undefined) {
      if (config.url.endsWith("/interactions")) data = interactions;
      else if (config.url.endsWith("/stream/status"))
        data = {
          active: false,
          state: "completed",
          recoverable: false,
          base_count: 0,
          user_input: "",
        };
      else if (config.url.endsWith("/messages"))
        data = {
          messages: storedMessages ?? [{ id: config.url, role: "user", content: config.url }],
        };
      else if (config.url === "/threads" && config.method === "post")
        data = { id: "u-1001-new", title: "new" };
      else if (config.method === "patch") data = { title: JSON.parse(config.data).title };
      else if (config.method === "delete") data = null;
      else data = history;
    }
    return {
      data: { code: "0", message: "ok", data },
      status: 200,
      statusText: "OK",
      headers: {},
      config,
    };
  };
  const chat = useChatStore();
  return {
    chat,
    calls,
    values,
    setInteractions: (value) => {
      interactions = value;
    },
    setHistory: (value) => {
      storedMessages = value;
    },
    intercept: (fn) => {
      intercept = fn;
    },
    close() {
      chat.reset();
      disposePinia(pinia);
      http.defaults.adapter = originalAdapter;
      global.fetch = originalFetch;
      global.localStorage = originalStorage;
    },
  };
}

test("restore selected thread and pending interactions exactly once", async () => {
  const env = mount();
  try {
    env.values.set("astra.active_thread.u-1001", "u-1001-one");
    await env.chat.initialize();
    await env.chat.initialize();
    assert.equal(env.chat.threadId, "u-1001-one");
    assert.equal(env.calls.filter((call) => call.url.endsWith("/messages")).length, 1);
    assert.equal(env.calls.filter((call) => call.url.endsWith("/interactions")).length, 1);
  } finally {
    env.close();
  }
});

test("new conversation sends once and preserves multiple assistant phases", async () => {
  const env = mount();
  env.setHistory([
    { id: "user", role: "user", content: "question" },
    { id: "first", role: "assistant", content: "first answer", reasoning: "first thought" },
    {
      id: "second",
      role: "assistant",
      content: "second answer",
      reasoning: "second thought",
      artifacts: [{ file_id: "f", filename: "report.pdf" }],
    },
  ]);
  let count = 0;
  let request;
  global.fetch = async (_, init) => {
    count++;
    request = init;
    return stream([
      { type: "reasoning.delta", delta: "first thought" },
      { type: "message.delta", delta: "first answer" },
      { type: "assistant.start" },
      { type: "reasoning.delta", delta: "second thought" },
      { type: "message.delta", delta: "second answer" },
      { type: "artifact.created", artifact: { file_id: "f", filename: "report.pdf" } },
    ]);
  };
  try {
    env.chat.draft = "question";
    await Promise.all([env.chat.send(), env.chat.send()]);
    assert.equal(count, 1);
    assert.equal(JSON.parse(request.body).thread_id, "u-1001-new");
    assert.equal(request.headers["X-User-Id"], "u-1001");
    assert.equal(env.chat.messages.length, 3);
    assert.equal(env.chat.messages[1].content, "first answer");
    assert.equal(env.chat.messages[2].reasoning, "second thought");
    assert.equal(env.chat.messages[2].artifacts[0].file_id, "f");
    assert.equal(env.chat.status, "idle");
    assert.equal(env.calls.filter((call) => call.url.endsWith("/interactions")).length, 1);
  } finally {
    env.close();
  }
});

test("pending approval blocks a new message and resumes without duplicate user bubble", async () => {
  const env = mount();
  let sent = 0;
  global.fetch = async (url) => {
    assert.match(url, /\/resume$/);
    sent++;
    env.setInteractions({ approvals: [], questions: [] });
    return stream([{ type: "message.delta", delta: "done" }]);
  };
  try {
    env.setInteractions({ approvals: [{ id: "approval", status: "pending" }], questions: [] });
    await env.chat.selectThread("u-1001-one");
    env.chat.draft = "blocked";
    await env.chat.send();
    assert.equal(sent, 0);
    await env.chat.resume({ id: "approval", approve: true });
    assert.equal(sent, 1);
    assert.equal(env.chat.messages.filter((message) => message.role === "user").length, 1);
    assert.equal(env.chat.approvals.length, 0);
  } finally {
    env.close();
  }
});

test("stop aborts stream and restores pending server interactions", async () => {
  const env = mount();
  const started = deferred();
  let signal;
  global.fetch = (_, init) =>
    new Promise((_, reject) => {
      signal = init.signal;
      started.resolve();
      signal.addEventListener("abort", () => reject(new DOMException("Stopped", "AbortError")));
    });
  try {
    await env.chat.selectThread("u-1001-one");
    env.chat.draft = "question";
    const pending = env.chat.send();
    await started.promise;
    await env.chat.stop();
    await pending;
    assert.equal(signal.aborted, true);
    assert.equal(env.chat.busy, false);
    assert.equal(env.chat.error, null);
    assert.equal(env.chat.sending, false);
  } finally {
    env.close();
  }
});

test("late stream cannot change the conversation after reset and selection", async () => {
  const env = mount();
  const started = deferred(),
    late = deferred();
  global.fetch = async () => {
    started.resolve();
    return late.promise;
  };
  try {
    await env.chat.selectThread("u-1001-one");
    env.chat.draft = "old question";
    const pending = env.chat.send();
    await started.promise;
    env.chat.reset();
    await env.chat.selectThread("u-1001-two");
    const before = JSON.stringify(env.chat.messages);
    late.resolve(stream([{ type: "message.delta", delta: "stale answer" }]));
    await pending;
    assert.equal(env.chat.threadId, "u-1001-two");
    assert.equal(JSON.stringify(env.chat.messages), before);
    assert.equal(env.chat.status, "idle");
  } finally {
    env.close();
  }
});

test("late history does not overwrite a reset conversation", async () => {
  const env = mount();
  const started = deferred(),
    late = deferred();
  env.intercept(async (config) => {
    if (config.url.endsWith("/messages")) {
      started.resolve();
      return late.promise;
    }
  });
  try {
    const pending = env.chat.selectThread("u-1001-one");
    await started.promise;
    env.chat.reset();
    late.resolve({ messages: [{ id: "stale", role: "user", content: "old" }] });
    await pending;
    assert.equal(env.chat.threadId, null);
    assert.deepEqual(env.chat.messages, []);
    assert.equal(env.chat.switching, false);
  } finally {
    env.close();
  }
});

test("manual refresh reloads current messages without losing the draft", async () => {
  const env = mount();
  try {
    await env.chat.initialize();
    await env.chat.selectThread("u-1001-one");
    env.chat.draft = "unsent draft";
    env.intercept((config) => {
      if (config.url.endsWith("/messages"))
        return { messages: [{ id: "updated", role: "assistant", content: "latest reply" }] };
    });
    assert.equal(await env.chat.refreshCurrent(), true);
    assert.equal(env.chat.messages[0].content, "latest reply");
    assert.equal(env.chat.draft, "unsent draft");
    assert.equal(env.chat.threadId, "u-1001-one");
    assert.equal(env.calls.filter((call) => call.url.endsWith("/messages")).length, 2);
    assert.equal(env.calls.filter((call) => call.url.endsWith("/interactions")).length, 2);
  } finally {
    env.close();
  }
});

test("rename and delete update the shared sidebar and active conversation", async () => {
  const env = mount();
  try {
    await env.chat.initialize();
    await env.chat.selectThread("u-1001-one");
    await env.chat.renameThread("u-1001-one", "renamed");
    assert.equal(env.chat.title, "renamed");
    await env.chat.deleteThread("u-1001-one");
    assert.equal(env.chat.threadId, null);
    assert.equal(
      env.chat.threads.some((thread) => thread.id === "u-1001-one"),
      false,
    );
    assert.deepEqual(env.chat.messages, []);
  } finally {
    env.close();
  }
});

function interruptedFailure(id = "failure-1") {
  return {
    id,
    occurred_at: "2026-10-07T10:05:26Z",
    reason: "server_shutdown",
    error_type: "CancelledError",
    message: "任务执行中断",
    stage: "tool",
    tool_name: "task",
    request_id: id,
    persisted: true,
  };
}

test("terminal history corrects completed parallel tasks whose SSE endings were lost", async () => {
  const env = mount();
  const failure = interruptedFailure();
  env.setHistory([
    { id: "user", role: "user", content: "写报告" },
    {
      id: "calls",
      role: "assistant",
      content: "",
      tools: [
        { id: "logical-a", name: "task", status: "success", result: "第七章完成" },
        { id: "logical-b", name: "task", status: "success", result: "第八章完成" },
      ],
    },
    { id: failure.id, role: "assistant", content: "", failure },
  ]);
  global.fetch = async () =>
    stream([
      { type: "tool.start", name: "task", call_id: "sdk-a" },
      { type: "tool.start", name: "task", call_id: "sdk-b" },
      { type: "tool.end", name: "task", call_id: "sdk-b", ok: true, result: "第八章完成" },
      { type: "error", error: failure.message, failure },
      { type: "done" },
    ]);
  try {
    env.chat.draft = "写报告";
    await env.chat.send();
    assert.deepEqual(
      env.chat.messages
        .flatMap((message) => message.tools ?? [])
        .map((tool) => [tool.id, tool.status]),
      [
        ["logical-a", "success"],
        ["logical-b", "success"],
      ],
    );
    assert.equal(env.chat.messages.filter((message) => message.failure).length, 1);
  } finally {
    env.close();
  }
});

test("checkpoint recovery replaces earlier tool attempts but keeps distinct failure records", async () => {
  const env = mount();
  const failures = [interruptedFailure("failure-1"), interruptedFailure("failure-2")];
  failures[1].occurred_at = "2026-10-07T10:06:29Z";
  const history = [
    { id: "user", role: "user", content: "写报告" },
    {
      id: "call",
      role: "assistant",
      content: "",
      tools: [{ id: "logical-task", name: "task", status: "interrupted" }],
    },
    ...failures.map((failure) => ({ id: failure.id, role: "assistant", content: "", failure })),
  ];
  let recovered = false;
  env.setHistory(history);
  env.intercept((config) =>
    config.url.endsWith("/stream/status")
      ? {
          active: false,
          state: recovered ? "completed" : "interrupted",
          recoverable: !recovered,
          checkpoint_id: "checkpoint-1",
          requires_tool_confirmation: true,
        }
      : undefined,
  );
  global.fetch = async (url) => {
    assert.match(url, /\/recover$/);
    recovered = true;
    env.setHistory([
      history[0],
      {
        ...history[1],
        tools: [{ id: "logical-task", name: "task", status: "success", result: "第七章完成" }],
      },
      ...history.slice(2),
      { id: "next", role: "assistant", content: "继续第八章" },
    ]);
    return stream([
      { type: "tool.start", name: "task", call_id: "new-sdk-run" },
      { type: "tool.end", name: "task", call_id: "new-sdk-run", ok: true, result: "第七章完成" },
      { type: "assistant.start" },
      { type: "message.delta", delta: "继续第八章" },
      { type: "done" },
    ]);
  };
  try {
    await env.chat.selectThread("u-1001-one");
    await env.chat.resumeInterrupted(true);
    assert.deepEqual(
      env.chat.messages
        .flatMap((message) => message.tools ?? [])
        .map((tool) => [tool.id, tool.status]),
      [["logical-task", "success"]],
    );
    assert.deepEqual(
      env.chat.messages.filter((message) => message.failure).map((message) => message.failure.id),
      ["failure-1", "failure-2"],
    );
    assert.equal(env.chat.messages.at(-1).content, "继续第八章");
  } finally {
    env.close();
  }
});

test("late terminal history cannot replace a newly selected conversation", async () => {
  const env = mount();
  const reading = deferred(),
    late = deferred();
  env.intercept(async (config) => {
    if (config.url === "/threads/u-1001-new/messages") {
      reading.resolve();
      return late.promise;
    }
    if (config.url === "/threads/u-1001-two/messages")
      return { messages: [{ id: "new-thread", role: "assistant", content: "新会话内容" }] };
  });
  global.fetch = async () =>
    stream([{ type: "message.delta", delta: "旧会话输出" }, { type: "done" }]);
  try {
    env.chat.draft = "旧会话";
    const sending = env.chat.send();
    await reading.promise;
    await env.chat.selectThread("u-1001-two");
    late.resolve({ messages: [{ id: "old-thread", role: "assistant", content: "过期历史" }] });
    await sending;
    assert.equal(env.chat.threadId, "u-1001-two");
    assert.equal(env.chat.messages[0].content, "新会话内容");
    assert.equal(env.chat.error, null);
  } finally {
    env.close();
  }
});

for (const status of [400, 429]) {
  test(`a rejected ${status} request retains its input and attachments`, async () => {
    const env = mount();
    env.setHistory([{ id: "old", role: "assistant", content: "上一轮已完成" }]);
    global.fetch = async () =>
      new Response(JSON.stringify({ code: String(status), message: "输入被拒绝", data: null }), {
        status,
      });
    const attachment = { fileId: "source", filename: "资料.pdf", contentType: "application/pdf" };
    try {
      env.chat.items.push({ id: "upload", status: "done", localUrl: "blob:test", attachment });
      env.chat.draft = "无法提交的输入";
      await env.chat.send();
      assert.match(env.chat.error, /输入被拒绝/);
      assert.equal(env.chat.status, "error");
      const user = env.chat.messages.find((message) => message.role === "user");
      assert.equal(user.content, "无法提交的输入");
      assert.equal(user.attachments[0].fileId, "source");
      assert.equal(env.calls.filter((call) => call.url.endsWith("/messages")).length, 0);
    } finally {
      env.close();
    }
  });
}

test("an unpersisted failure retains the partial answer and its failure details", async () => {
  const env = mount();
  const failure = { ...interruptedFailure(), persisted: false };
  env.setHistory([{ id: "user", role: "user", content: "写报告" }]);
  env.intercept((config) =>
    config.url.endsWith("/stream/status")
      ? { active: false, state: "failed", recoverable: false }
      : undefined,
  );
  global.fetch = async () =>
    stream([
      { type: "message.delta", delta: "尚未保存的报告正文" },
      { type: "error", error: failure.message, failure },
      { type: "done" },
    ]);
  try {
    env.chat.draft = "写报告";
    await env.chat.send();
    const partial = env.chat.messages.find((message) => message.failure);
    assert.equal(partial.content, "尚未保存的报告正文");
    assert.equal(partial.failure.persisted, false);
    assert.equal(partial.failure.id, failure.id);
    assert.equal(env.calls.filter((call) => call.url.endsWith("/messages")).length, 0);
  } finally {
    env.close();
  }
});

test("a task finishing before rejoin restores history even without a stream event", async () => {
  const env = mount();
  const restored = deferred();
  let running = true;
  let reads = 0;
  env.intercept((config) => {
    if (config.url.endsWith("/stream/status"))
      return {
        active: running,
        state: running ? "running" : "completed",
        recoverable: false,
        base_count: 0,
        user_input: "后台任务",
      };
    if (config.url.endsWith("/messages")) {
      if (++reads === 2) restored.resolve();
      return {
        messages: [
          { id: "user", role: "user", content: "后台任务" },
          { id: "answer", role: "assistant", content: "已经完成的正文" },
        ],
      };
    }
  });
  global.fetch = async () => {
    running = false;
    return new Response(null, { status: 404 });
  };
  try {
    await env.chat.selectThread("u-1001-one");
    await restored.promise;
    await new Promise(setImmediate);
    assert.equal(env.chat.messages.at(-1).content, "已经完成的正文");
    assert.equal(env.chat.messages.filter((message) => message.role === "assistant").length, 1);
  } finally {
    env.close();
  }
});

test("a disconnected stream keeps the background task running and can rejoin it", async () => {
  const env = mount();
  let running = true;
  const rejoined = deferred();
  env.intercept((config) => {
    if (config.url.endsWith("/stream/status"))
      return {
        active: running,
        state: running ? "running" : "completed",
        recoverable: false,
        base_count: 0,
        user_input: "后台任务",
      };
    if (config.url.endsWith("/messages")) {
      if (!running) rejoined.resolve();
      return {
        messages: running
          ? [{ id: "user", role: "user", content: "后台任务" }]
          : [
              { id: "user", role: "user", content: "后台任务" },
              { id: "answer", role: "assistant", content: "后台已完成" },
            ],
      };
    }
  });
  global.fetch = async () => stream([{ type: "tool.start", name: "task", call_id: "active-task" }]);
  try {
    env.chat.draft = "后台任务";
    await env.chat.send();
    assert.equal(env.chat.messages.flatMap((message) => message.tools ?? [])[0].status, "running");
    assert.ok(!env.chat.messages.some((message) => message.failure));
    assert.match(env.chat.error, /仍在后台运行/);
    env.chat.draft = "不能重复提交";
    assert.equal(env.chat.canSend, false);
    assert.equal(env.calls.filter((call) => call.url.endsWith("/messages")).length, 0);

    global.fetch = async (url) => {
      assert.match(url, /\/stream$/);
      running = false;
      return stream([{ type: "message.delta", delta: "后台已完成" }, { type: "done" }]);
    };
    await env.chat.selectThread(env.chat.threadId, true);
    await rejoined.promise;
    await new Promise(setImmediate);
    assert.equal(env.chat.messages.at(-1).content, "后台已完成");
    assert.equal(env.chat.error, null);
    assert.equal(env.chat.busy, false);
  } finally {
    env.close();
  }
});
