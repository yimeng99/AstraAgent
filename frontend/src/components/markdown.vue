<script setup lang="ts">
import MarkdownRender from "markstream-vue";
defineProps<{ content: string; streaming?: boolean }>();
const emit = defineEmits<{ fileLink: [url: string] }>();
function onLink(event: MouseEvent) {
  const anchor = (event.target as Element | null)?.closest("a[href]");
  if (!anchor) return;
  const url = new URL(anchor.getAttribute("href") || "", location.origin);
  if (
    url.origin !== location.origin ||
    !/^\/api\/v1\/threads\/[^/]+\/sandbox\/content$/.test(url.pathname)
  )
    return;
  event.preventDefault();
  event.stopPropagation();
  emit("fileLink", url.pathname + url.search);
}
</script>
<template>
  <!-- 模型输出不可信：原始 HTML 展示为文本，流完成后才按完整文档收尾。 -->
  <div @click.capture="onLink">
    <MarkdownRender
      class="markdown"
      :class="{ 'streaming-output': streaming }"
      mode="chat"
      :max-live-nodes="80"
      :live-node-buffer="12"
      :node-virtual="true"
      :defer-nodes-until-visible="true"
      :fade="false"
      :content="content"
      :final="!streaming"
      :smooth-streaming="!!streaming"
      :parse-coalesce-ms="32"
      html-policy="escape"
    />
  </div>
</template>
