<script setup lang="ts">
import { ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { filesApi } from "@/api/files";
import type { SandboxEntry as Entry } from "@/types/files";
import { formatSize } from "@/utils/files";
import { Close, Refresh, File as FileIcon } from "./icons";
import type { PreviewTarget } from "@/types/files";

const props = defineProps<{ threadId: string | null; userId: string; busy: boolean }>();
const emit = defineEmits<{ close: []; preview: [target: PreviewTarget] }>();
const entries = ref<Entry[]>([]),
  error = ref(""),
  loading = ref(false),
  acting = ref(false);
let version = 0;
async function refresh() {
  const current = ++version;
  entries.value = [];
  error.value = "";
  if (!props.threadId || props.busy) {
    loading.value = false;
    return;
  }
  loading.value = true;
  try {
    const data = await filesApi.list(props.userId, props.threadId);
    if (current === version) entries.value = data.entries;
  } catch (issue) {
    if (current === version) error.value = (issue as Error).message;
  } finally {
    if (current === version) loading.value = false;
  }
}
watch(
  () => [props.threadId, props.userId],
  () => {
    void refresh();
  },
  { immediate: true },
);
watch(
  () => props.busy,
  (busy, previous) => {
    if (previous && !busy) void refresh();
  },
);
async function mutate(operation: () => Promise<unknown>) {
  const selectedThread = props.threadId;
  acting.value = true;
  try {
    await operation();
    if (selectedThread === props.threadId) await refresh();
  } catch (issue) {
    ElMessage.error((issue as Error).message);
  } finally {
    acting.value = false;
  }
}
async function nameOperation(entry: Entry) {
  const selectedThread = props.threadId;
  try {
    const result = await ElMessageBox.prompt("请输入新名称", "重命名", {
      inputValue: entry?.name || "",
      inputValidator: (value) =>
        (!!value.trim() && !/[\\/\r\n]/.test(value) && ![".", ".."].includes(value)) ||
        "请输入有效名称",
      confirmButtonText: "确定",
      cancelButtonText: "取消",
    });
    if (selectedThread !== props.threadId) return;
    if (!selectedThread) return;
    await mutate(() => filesApi.rename(props.userId, selectedThread, entry.path, result.value));
  } catch {
    /* 取消不改变文件。 */
  }
}
async function remove(entry: Entry) {
  const selectedThread = props.threadId;
  try {
    await ElMessageBox.confirm(
      `删除“${entry.name}”${entry.directory ? "及其全部内容" : ""}？此操作无法撤销。`,
      "删除文件",
      { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" },
    );
    if (selectedThread !== props.threadId) return;
    if (!selectedThread) return;
    await mutate(() => filesApi.remove(props.userId, selectedThread, entry.path));
  } catch {
    /* 取消不改变文件。 */
  }
}
async function open(entry: Entry, download = false) {
  const selectedThread = props.threadId;
  acting.value = true;
  try {
    if (!selectedThread) return;
    const blob = await filesApi.content(props.userId, selectedThread, entry.path, download);
    if (selectedThread !== props.threadId) return;
    const url = URL.createObjectURL(blob);
    const downloadLatest = async () => {
      if (selectedThread === props.threadId) await open(entry, true);
    };
    if (download) {
      const link = document.createElement("a");
      link.href = url;
      link.download = entry.name;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } else {
      emit("preview", {
        fileId: entry.path,
        filename: entry.name,
        url,
        size: entry.size,
        download: downloadLatest,
      });
    }
  } catch (issue) {
    ElMessage.error((issue as Error).message);
  } finally {
    acting.value = false;
  }
}
</script>

<template>
  <aside class="sandbox-panel" aria-label="当前会话文件">
    <header>
      <div><strong>会话文件</strong><small>保存在你的云端工作空间</small></div>
      <div class="sandbox-actions">
        <el-button
          size="small"
          text
          :icon="Refresh"
          :loading="loading"
          :disabled="!threadId || busy || acting"
          aria-label="刷新文件"
          @click="refresh"
        />
        <el-button text circle :icon="Close" aria-label="关闭文件面板" @click="emit('close')" />
      </div>
    </header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div v-loading="loading" class="sandbox-entries">
      <el-empty
        v-if="!entries.length && !loading && !error"
        :image-size="56"
        :description="threadId ? '当前会话暂无文件' : '开始会话后查看文件'"
      />
      <div v-for="entry in entries" :key="entry.path" class="sandbox-entry">
        <button class="sandbox-file" :disabled="acting || busy" @click="open(entry)">
          <el-icon><FileIcon /></el-icon
          ><span
            ><strong>{{ entry.name }}</strong
            ><small>{{ entry.directory ? "文件夹" : formatSize(entry.size) }}</small></span
          >
        </button>
        <el-dropdown
          trigger="click"
          placement="bottom-end"
          :teleported="true"
          :disabled="acting || busy"
          @command="
            (command: string) =>
              command === 'download'
                ? open(entry, true)
                : command === 'rename'
                  ? nameOperation(entry)
                  : remove(entry)
          "
        >
          <el-button text circle aria-label="文件操作">⋯</el-button
          ><template #dropdown
            ><el-dropdown-menu
              ><el-dropdown-item v-if="!entry.directory" command="download">下载</el-dropdown-item
              ><el-dropdown-item command="rename">重命名</el-dropdown-item
              ><el-dropdown-item command="delete" divided>删除</el-dropdown-item></el-dropdown-menu
            ></template
          >
        </el-dropdown>
      </div>
    </div>
    <footer>文件生成或编辑完成后自动刷新 · 单文件最大 20 MiB</footer>
  </aside>
</template>

<style scoped>
.sandbox-panel {
  box-sizing: border-box;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  width: 320px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-left: 1px solid #e7eaf0;
  background: #fff;
  padding: 20px 16px 12px;
}
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 36px;
}
header strong {
  font-size: 15px;
}
header small {
  display: block;
  margin-top: 5px;
  color: #929cab;
  font-size: 12px;
}
.sandbox-actions {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}
.sandbox-path {
  font-size: 12px;
  color: #929cab;
  margin-bottom: 14px;
  overflow-wrap: anywhere;
}
.sandbox-path button {
  border: 0;
  background: none;
  padding: 0;
  color: #63718a;
  cursor: pointer;
}
.sandbox-path span {
  padding: 0 8px;
}
.sandbox-path p {
  margin: 8px 0 0;
}
.sandbox-entries {
  margin-top: 16px;
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  min-height: 0;
}
.sandbox-entry {
  display: flex;
  align-items: center;
  padding: 8px 4px;
  border-radius: 6px;
}
.sandbox-entry:hover {
  background: #f7f8fa;
}
.sandbox-file {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
  padding: 0;
  border: 0;
  background: none;
  text-align: left;
  cursor: pointer;
  color: #43536d;
}
.sandbox-file:disabled {
  cursor: default;
}
.sandbox-file > i,
.sandbox-file > .el-icon {
  font-size: 21px;
  color: #7894b9;
}
.sandbox-file span {
  flex: 1;
  min-width: 0;
}
.sandbox-file strong {
  display: block;
  font-size: 13px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sandbox-file small {
  display: block;
  margin-top: 5px;
  font-size: 11px;
  color: #9ba5b3;
}
footer {
  font-size: 10px;
  color: #9ba5b3;
  margin-top: 12px;
  line-height: 1.5;
}
@media (max-width: 1000px) {
  .sandbox-panel {
    position: fixed;
    right: 0;
    top: 0;
    bottom: 0;
    z-index: 20;
    width: min(360px, 100vw);
    box-shadow: -8px 0 24px #17233b18;
  }
}
</style>
