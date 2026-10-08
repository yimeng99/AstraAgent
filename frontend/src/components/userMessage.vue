<script setup lang="ts">
import { ElMessage } from "element-plus";
import { computed } from "vue";
import type { ChatMessage } from "@/types/chat";
import type { PreviewTarget } from "@/types/files";
import { formatSize } from "@/utils/files";
import Markdown from "./markdown.vue";
import { File } from "./icons";

const props = defineProps<{ message: ChatMessage }>();
const timeLabel = computed(() => {
  if (!props.message.createdAt) return "";
  const date = new Date(props.message.createdAt);
  if (Number.isNaN(date.getTime())) return "";
  return `${date.getMonth() + 1}月${date.getDate()}日 ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
});
defineEmits<{ preview: [target: PreviewTarget]; fileLink: [url: string] }>();

async function copyContent() {
  try {
    await navigator.clipboard.writeText(props.message.content);
    ElMessage.success("已复制");
  } catch {
    ElMessage.error("复制失败，请手动选择文字复制");
  }
}
</script>

<template>
  <article class="user-message" aria-label="用户消息">
    <div class="user-bubble">
      <Markdown
        v-if="message.content.trim()"
        :content="message.content"
        @file-link="$emit('fileLink', $event)"
      />
      <div v-if="message.attachments?.length" class="file-list">
        <button
          v-for="file in message.attachments"
          :key="file.fileId"
          type="button"
          class="file-card"
          @click="
            $emit('preview', {
              fileId: file.fileId,
              filename: file.filename,
              url: file.previewUrl,
              size: file.size,
            })
          "
        >
          <img v-if="file.kind === 'image'" :src="file.previewUrl" :alt="file.filename" />
          <el-icon v-else><File /></el-icon>
          <span
            >{{ file.filename }}<small>{{ formatSize(file.size) }}</small></span
          >
        </button>
      </div>
    </div>
    <div class="message-meta">
      <time v-if="timeLabel" :datetime="message.createdAt">{{ timeLabel }}</time>
      <el-tooltip v-if="message.content" content="复制" placement="bottom">
        <button class="icon-button" type="button" aria-label="复制用户消息" @click="copyContent">
          <i class="ri-file-copy-line" aria-hidden="true" />
        </button>
      </el-tooltip>
    </div>
  </article>
</template>

<style scoped lang="scss">
.user-message {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
  margin: 0 0 16px auto;
  max-width: 80%;
  width: fit-content;
  font-size: 14px;
  line-height: 1.85;
  overflow-wrap: anywhere;
}
.user-bubble {
  min-width: 0;
  max-width: 100%;
  padding: 12px 18px;
  border-radius: 16px;
  background: #f1f4f8;
  :deep(.paragraph-node:first-child) {
    margin-top: 0;
  }
  :deep(.paragraph-node:last-child) {
    margin-bottom: 0;
  }
}
.message-meta {
  display: flex;
  align-items: center;
  gap: 16px;
  min-height: 28px;
  color: #8993a4;
  font-size: 12px;
  white-space: nowrap;
  opacity: 0;
  pointer-events: none;
  transition: opacity 150ms ease;
}
.user-message:hover .message-meta {
  opacity: 1;
  pointer-events: auto;
}
@media (max-width: 768px) {
  .user-message {
    max-width: 90%;
  }
}
</style>
