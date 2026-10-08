<script setup lang="ts">
import { computed, ref } from "vue";
import type { ApprovalInfo, ResumeRequest } from "@/types/chat";
const props = defineProps<{ items: ApprovalInfo[]; busy: boolean }>();
const pendingItems = computed(() => props.items.filter((item) => item.status === "pending"));
const emit = defineEmits<{ resume: [request: ResumeRequest] }>();
const expanded = ref<Record<string, boolean>>({});
function description(item: ApprovalInfo) {
  const names: Record<string, string> = {
    render_document: "生成文档",
    render_spreadsheet: "生成 Excel 报表",
    import_session_file: "导入其他会话的文件",
    write_file: "写入文件",
    edit_file: "修改文件",
  };
  const filename = item.args.filename ?? item.args.file_path ?? item.args.path;
  return `${names[item.tool] ?? "执行一项操作"}${typeof filename === "string" ? `：${filename.split(/[\\/]/).pop()}` : ""}`;
}
function summary(item: ApprovalInfo) {
  const title = item.args.title;
  if (typeof title === "string" && title.trim()) return title;
  return item.tool.startsWith("render_")
    ? "按当前方案生成文件，完成后可在对话中预览和下载。"
    : "确认后执行当前操作，并继续完成任务。";
}
</script>
<template>
  <div class="approvals" aria-live="polite">
    <section
      v-for="item in pendingItems"
      :key="item.id"
      class="approval-card"
    >
      <div class="confirmation-heading">
        <i class="ri-shield-check-line" aria-hidden="true" />
        <div>
          <span class="confirmation-label">{{
            item.resume_ready ? "可以继续任务" : "需要你的确认"
          }}</span
          ><strong>{{ description(item) }}</strong>
        </div>
        <span class="confirmation-status">已挂起</span>
      </div>
      <p class="confirmation-description">
        {{ item.resume_ready ? "你的选择已保存，继续即可恢复任务。" : summary(item) }}
      </p>
      <el-button
        text
        size="small"
        class="confirmation-toggle"
        :aria-expanded="!!expanded[item.id]"
        @click="expanded[item.id] = !expanded[item.id]"
        >{{ expanded[item.id] ? "收起技术详情" : "查看技术详情"
        }}<i :class="expanded[item.id] ? 'ri-arrow-up-s-line' : 'ri-arrow-down-s-line'"
      /></el-button>
      <div v-if="expanded[item.id]" class="confirmation-details">
        <p>工具：{{ item.tool }}</p>
        <div v-for="(value, key) in item.args" :key="key" class="approval-parameters">
          <span>{{ key === "code" ? "执行代码" : key }}</span>
          <pre>{{ typeof value === "string" ? value : JSON.stringify(value, null, 2) }}</pre>
        </div>
      </div>
      <div class="confirmation-footer">
        <small>进度已保存，可稍后处理</small>
        <div class="approval-actions">
          <el-button
            v-if="!item.resume_ready"
            :disabled="busy"
            @click="emit('resume', { id: item.id, approve: false })"
            >不执行</el-button
          >
          <el-button
            type="primary"
            :disabled="busy"
            @click="
              emit('resume', item.resume_ready ? { id: item.id } : { id: item.id, approve: true })
            "
            >{{ item.resume_ready ? "继续任务" : "确认执行" }}</el-button
          >
        </div>
      </div>
    </section>
    <div v-if="pendingItems.length > 1" class="batch-actions">
      <span>本次共 {{ pendingItems.length }} 项操作</span>
      <el-button :disabled="busy" @click="emit('resume', { ids: pendingItems.map(item => item.id), approve: false })">全部不执行</el-button>
      <el-button type="primary" :loading="busy" :disabled="busy" @click="emit('resume', { ids: pendingItems.map(item => item.id), approve: true })">确认全部</el-button>
    </div>
  </div>
</template>
<style scoped>
.batch-actions {
  position: sticky;
  bottom: 0;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 16px 0 4px;
  background: white;
  border-top: 1px solid #ebeef5;
}
.batch-actions > span { flex: 1; color: #64748b; font-size: 14px; }
.approval-card {
  padding: 0;
  background: transparent;
  border: 0;
  border-radius: 0;
  margin-bottom: 24px;
}
.confirmation-heading {
  display: flex;
  align-items: center;
  gap: 12px;
}
.confirmation-heading > i {
  display: none;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: #eef4ff;
  color: #3469da;
  font-size: 20px;
  flex-shrink: 0;
}
.confirmation-heading > div {
  flex: 1;
  min-width: 0;
}
.confirmation-label {
  display: block;
  color: #8a94a6;
  font-size: 12px;
  margin-bottom: 4px;
}
.confirmation-heading strong {
  display: block;
  font-size: 15px;
  overflow-wrap: anywhere;
}
.confirmation-status {
  display: none;
  font-size: 12px;
  color: #8a94a6;
  white-space: nowrap;
}
.confirmation-description {
  margin: 14px 0 6px;
  color: #64748b;
  font-size: 14px;
  line-height: 1.6;
}
.confirmation-toggle {
  padding: 4px 0;
  color: #8a94a6;
}
.confirmation-details {
  max-height: 200px;
  overflow: auto;
  margin: 8px 0 16px;
  padding: 12px;
  background: #f7f8fa;
  border-radius: 8px;
  font-size: 12px;
}
.confirmation-details pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.confirmation-footer {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 14px;
  padding-top: 0;
  border-top: 0;
}
.confirmation-footer small {
  order: 2;
}
.confirmation-footer small {
  color: #98a2b3;
  font-size: 12px;
}
.approval-actions {
  margin-top: 0;
}
</style>
