<script setup lang="ts">
import { ref, shallowRef, computed, watch, defineAsyncComponent } from "vue";
import type { Component } from "vue";
import { extOf } from "@/utils/files";
import { loadPreview } from "@/api/files";

const VueOfficeDocx = defineAsyncComponent(async () => {
  const [module] = await Promise.all([
    import("@vue-office/docx"),
    import("@vue-office/docx/lib/index.css"),
  ]);
  return module.default as unknown as Component;
});
const VueOfficeExcel = defineAsyncComponent(async () => {
  // Excel 的布局依赖组件 CSS，否则画布高度可能只显示两三行。
  const [module] = await Promise.all([
    import("@vue-office/excel"),
    import("@vue-office/excel/lib/index.css"),
  ]);
  return module.default as unknown as Component;
});
const VueOfficePdf = defineAsyncComponent(async () => {
  const module = await import("@vue-office/pdf");
  return module.default as unknown as Component;
});
import type { PreviewTarget } from "@/types/files";
const props = defineProps<{ target: PreviewTarget | null }>();
const emit = defineEmits<{ close: [] }>();
const source = shallowRef<ArrayBuffer>();
const text = ref(""),
  error = ref(""),
  loading = ref(false);
const ext = computed(() => extOf(props.target?.filename ?? ""));
const isOffice = computed(() => ["docx", "xlsx", "xls", "pdf"].includes(ext.value));
const isText = computed(
  () =>
    !isOffice.value &&
    (props.target?.text !== undefined || ["txt", "md", "csv", "json", "log"].includes(ext.value)),
);
function rendered() {
  loading.value = false;
}
function renderError() {
  loading.value = false;
  error.value = "文件预览失败，请下载原文件查看";
}
watch(
  () => props.target,
  async (target, _, cleanup) => {
    let disposed = false;
    const ac = new AbortController();
    cleanup(() => {
      disposed = true;
      ac.abort();
    });
    source.value = undefined;
    text.value = "";
    error.value = "";
    loading.value = false;
    if (!target) return;
    if (isText.value && target.text !== undefined) {
      text.value = target.text;
      return;
    }
    if (!isOffice.value && !isText.value) return;
    loading.value = true;
    try {
      const buffer = await loadPreview(target.url, ac.signal);
      if (disposed) return;
      if (isOffice.value) source.value = buffer;
      else {
        try {
          text.value = new TextDecoder("utf-8", { fatal: true }).decode(buffer);
        } catch {
          text.value = new TextDecoder("gb18030").decode(buffer);
        }
        loading.value = false;
      }
    } catch (issue) {
      if (!disposed) {
        error.value = (issue as Error).message;
        loading.value = false;
      }
    }
  },
);
</script>
<template>
  <el-dialog
    :model-value="!!target"
    :title="target?.filename"
    width="80%"
    destroy-on-close
    @close="emit('close')"
  >
    <div v-if="target" v-loading="loading" class="preview-body">
      <VueOfficeDocx
        v-if="ext === 'docx' && source"
        :key="target.url"
        :src="source"
        class="office-preview"
        @rendered="rendered"
        @error="renderError"
      />
      <VueOfficeExcel
        v-else-if="['xlsx', 'xls'].includes(ext) && source"
        :key="target.url"
        :src="source"
        :options="{ minColLength: 12, minRowLength: 14, showContextmenu: false }"
        class="office-preview"
        @rendered="rendered"
        @error="renderError"
      />
      <VueOfficePdf
        v-else-if="ext === 'pdf' && source"
        :key="target.url"
        :src="source"
        class="office-preview"
        @rendered="rendered"
        @error="renderError"
      />
      <img
        v-else-if="['png', 'jpg', 'jpeg', 'webp', 'gif'].includes(ext)"
        :src="target.url"
        :alt="target.filename"
      />
      <pre v-else-if="isText">{{ text }}</pre>
      <el-empty v-else-if="!isOffice" description="该格式暂不支持在线预览，请下载打开" />
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
    </div>
    <template #footer
      ><el-button @click="emit('close')">关闭</el-button
      ><el-button v-if="target?.download" type="primary" @click="target.download()"
        >下载文件</el-button
      ><el-button v-else tag="a" :href="target?.url" :download="target?.filename" type="primary"
        >下载文件</el-button
      ></template
    >
  </el-dialog>
</template>
