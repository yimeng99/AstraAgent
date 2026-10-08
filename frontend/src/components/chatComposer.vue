<script setup lang="ts">
import { ref } from "vue";
import ModelSelector from "./modelSelector/index.vue";
import { Plus, Top, Close } from "./icons";
import { ACCEPT_ATTR, formatSize } from "@/utils/files";
import type { UploadItem } from "@/types/files";
const props = defineProps<{
  items: UploadItem[];
  busy: boolean;
  sending: boolean;
  disabled: boolean;
  canSend: boolean;
  placeholder?: string;
}>();
const model = defineModel<string>({ required: true });
const emit = defineEmits<{
  send: [];
  stop: [];
  files: [files: FileList];
  retry: [id: string];
  remove: [id: string];
}>();
const fileInput = ref<HTMLInputElement>();
function onKey(event: KeyboardEvent) {
  if (props.disabled) return;
  // 中文输入法确认候选词的回车不能发送消息。
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
    event.preventDefault();
    emit("send");
  }
}
function chooseFiles(event: Event) {
  const input = event.target as HTMLInputElement;
  if (input.files) emit("files", input.files);
  input.value = "";
}
function paste(event: ClipboardEvent) {
  if (props.disabled) return;
  const files = event.clipboardData?.files;
  if (files?.length) {
    event.preventDefault();
    emit("files", files);
  }
}
function drop(event: DragEvent) {
  if (!props.busy && !props.disabled && event.dataTransfer?.files.length)
    emit("files", event.dataTransfer.files);
}
</script>
<template>
  <div class="composer" @dragover.prevent @drop.prevent="drop" @paste="paste">
    <div v-if="items.length" class="upload-list">
      <div v-for="item in items" :key="item.id" class="upload-item">
        <img v-if="item.kind === 'image'" :src="item.localUrl" :alt="item.filename" /><span
          >{{ item.filename
          }}<small v-if="item.status === 'uploading'"
            >上传中 {{ Math.round((item.progress ?? 0) * 100) }}%</small
          ><small v-else-if="item.error" class="error">{{ item.error }}</small
          ><small v-else>{{ formatSize(item.size) }}</small></span
        ><el-button v-if="item.status === 'error'" text @click="emit('retry', item.id)"
          >重试</el-button
        ><el-button
          text
          circle
          :icon="Close"
          :aria-label="`移除 ${item.filename}`"
          @click="emit('remove', item.id)"
        />
      </div>
    </div>
    <el-input
      v-model="model"
      type="textarea"
      :autosize="{ minRows: 2, maxRows: 8 }"
      :placeholder="placeholder ?? '发送消息或创建任务…'"
      :disabled="disabled"
      @keydown="onKey"
    />
    <div class="composer-actions">
      <input
        ref="fileInput"
        type="file"
        multiple
        :accept="ACCEPT_ATTR"
        hidden
        @change="chooseFiles"
      /><el-tooltip content="上传文件"
        ><el-button
          circle
          :icon="Plus"
          aria-label="上传文件"
          :disabled="busy || sending || disabled"
          @click="fileInput?.click()" /></el-tooltip
      ><span class="input-hint">Enter 发送 · Shift + Enter 换行</span
      ><ModelSelector :disabled="busy || sending || disabled" /><el-button
        v-if="busy"
        class="stop-button"
        type="primary"
        circle
        aria-label="停止生成"
        @click="emit('stop')"
        ><span class="stop-square" aria-hidden="true" /></el-button
      ><el-button
        v-else
        type="primary"
        circle
        :icon="Top"
        aria-label="发送消息"
        :disabled="!canSend"
        :loading="sending"
        @click="emit('send')"
      />
    </div>
  </div>
</template>

<style scoped lang="scss">
.composer-actions .stop-button {
  width: 34px;
  height: 34px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: var(--chat-run-color);
  color: #fff;
  &:hover {
    background: #3567db;
  }
  &:active {
    background: #2b59c5;
  }
  &:focus-visible {
    outline: 2px solid #a9c1fa;
    outline-offset: 3px;
  }
}
.stop-square {
  display: block;
  width: 10px;
  height: 10px;
  border-radius: 3px;
  background: currentColor;
}
</style>
