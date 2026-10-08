<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { QuestionInfo, ResumeRequest } from "@/types/chat";
const props = defineProps<{
  items: QuestionInfo[];
  busy: boolean;
  threadId: string | null;
  userId: string;
}>();
const emit = defineEmits<{ submit: [requests: ResumeRequest[]] }>();
const index = ref(0);
const collapsed = ref(false);
const drafts = ref<Record<string, string>>({});
const custom = ref<Record<string, boolean>>({});
const skipped = ref<Record<string, boolean>>({});
const pages = ref<QuestionInfo[]>([]);
const current = computed(() => pages.value[index.value]);
const key = computed(() => `astra:questions:${props.userId}:${props.threadId}`);
watch(
  key,
  () => {
    drafts.value = {};
    custom.value = {};
    skipped.value = {};
    index.value = 0;
    collapsed.value = false;
    pages.value = [];
    try {
      const saved = JSON.parse(sessionStorage.getItem(key.value) || "{}");
      drafts.value = saved.drafts || {};
      custom.value = saved.custom || {};
      skipped.value = saved.skipped || {};
    } catch {
      /* 浏览器禁用存储时，仍可在当前页面回答。 */
    }
  },
  { immediate: true },
);
watch(
  [() => props.items, () => props.busy],
  ([items]) => {
    if (props.busy) return;
    pages.value = items.filter((item) => item.status === "pending");
    index.value = Math.min(index.value, Math.max(0, pages.value.length - 1));
  },
  { immediate: true },
);
watch(
  [drafts, custom, skipped],
  () => {
    try {
      sessionStorage.setItem(
        key.value,
        JSON.stringify({ drafts: drafts.value, custom: custom.value, skipped: skipped.value }),
      );
    } catch {
      /* 保持输入可用。 */
    }
  },
  { deep: true },
);
const answered = (item: QuestionInfo) =>
  item.resume_ready || skipped.value[item.id] || !!drafts.value[item.id]?.trim();
const canContinue = computed(() => !!current.value && answered(current.value));
function next(skip = false) {
  if (props.busy || !current.value) return;
  if (skip) skipped.value[current.value.id] = true;
  if (!answered(current.value)) return;
  if (index.value < pages.value.length - 1) {
    index.value++;
    return;
  }
  const missing = pages.value.findIndex((item) => !answered(item));
  if (missing >= 0) {
    index.value = missing;
    return;
  }
  emit(
    "submit",
    pages.value.map((item) =>
      item.resume_ready
        ? { id: item.id }
        : {
            id: item.id,
            answer: skipped.value[item.id]
              ? "用户选择跳过此问题，暂不提供这项信息。请勿编造答案。"
              : drafts.value[item.id].trim(),
          },
    ),
  );
}
function choose(value: string) {
  if (!current.value) return;
  drafts.value[current.value.id] = value;
  custom.value[current.value.id] = false;
  skipped.value[current.value.id] = false;
}
</script>
<template>
  <section v-if="current" class="question-panel" aria-label="补充需求" :aria-busy="busy">
    <header class="question-heading">
      <span
        >补充需求<span v-if="collapsed"> · {{ index + 1 }} / {{ pages.length }}</span></span
      >
      <div>
        <button
          type="button"
          :aria-label="collapsed ? '展开问题' : '收起问题'"
          @click="collapsed = !collapsed"
        >
          <i :class="collapsed ? 'ri-arrow-up-s-line' : 'ri-arrow-down-s-line'" />
        </button>
        <button
          v-if="!collapsed"
          type="button"
          aria-label="稍后填写"
          title="收起并保留回答"
          @click="collapsed = true"
        >
          <i class="ri-close-line" />
        </button>
      </div>
    </header>
    <template v-if="!collapsed">
      <h3>{{ current.question }}</h3>
      <p v-if="current.resume_ready" class="saved-note">回答已保存，提交后继续任务。</p>
      <div v-else class="question-content">
        <div
          v-if="current.options.length"
          class="question-options"
          role="group"
          :aria-label="current.question"
        >
          <button
            v-for="(option, number) in current.options"
            :key="option"
            type="button"
            class="question-option"
            :class="{
              selected:
                !custom[current.id] && drafts[current.id] === option && !skipped[current.id],
            }"
            :aria-pressed="!custom[current.id] && drafts[current.id] === option"
            :disabled="busy"
            @click="choose(option)"
          >
            <span class="option-number">{{ number + 1 }}</span
            ><span>{{ option }}</span
            ><i v-if="!custom[current.id] && drafts[current.id] === option" class="ri-check-line" />
          </button>
          <button
            type="button"
            class="question-option custom-option"
            :disabled="busy"
            @click="
              custom[current.id] = true;
              drafts[current.id] = '';
              skipped[current.id] = false;
            "
          >
            <span class="option-number"><i class="ri-edit-box-line" /></span>输入你的答案
          </button>
        </div>
        <el-input
          v-if="!current.options.length || custom[current.id]"
          v-model="drafts[current.id]"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 5 }"
          :maxlength="3500"
          :disabled="busy"
          :aria-label="current.question"
          placeholder="输入你的答案"
          @input="skipped[current.id] = false"
        />
        <p v-if="skipped[current.id]" class="saved-note">已选择跳过，可重新填写。</p>
      </div>
      <footer class="question-footer">
        <nav aria-label="问题导航">
          <button
            type="button"
            aria-label="上一题"
            :disabled="busy || index === 0"
            @click="index--"
          >
            <i class="ri-arrow-left-s-line" /></button
          ><span>{{ index + 1 }} / {{ pages.length }}</span
          ><button
            type="button"
            aria-label="下一题预览"
            :disabled="busy || index === pages.length - 1"
            @click="index++"
          >
            <i class="ri-arrow-right-s-line" />
          </button>
        </nav>
        <div class="question-buttons">
          <el-button :disabled="busy || current.resume_ready" @click="next(true)">跳过</el-button
          ><el-button
            class="question-next"
            :disabled="busy || !canContinue"
            :loading="busy"
            @click="next()"
            >{{ index === pages.length - 1 ? "提交" : "下一题" }}</el-button
          >
        </div>
      </footer>
    </template>
  </section>
</template>
<style scoped>
.question-panel {
  padding: 22px 24px 14px;
  border: 1px solid #e7e7e9;
  border-radius: 22px;
  background: white;
  box-shadow: 0 3px 16px #00000005;
  color: #202124;
}
.question-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: #858993;
  font-size: 12px;
}
.question-heading button,
nav button {
  border: 0;
  background: transparent;
  color: #858993;
  width: 30px;
  height: 30px;
  cursor: pointer;
  font-size: 18px;
  border-radius: 6px;
}
button:focus-visible {
  outline: 2px solid #789be3;
  outline-offset: 2px;
}
button:disabled {
  opacity: 0.4;
  cursor: default;
}
h3 {
  font-size: 17px;
  font-weight: 500;
  margin: 2px 0 16px;
  line-height: 1.6;
}
.question-content {
  max-height: 36vh;
  overflow-y: auto;
}
.question-options {
  display: grid;
  gap: 4px;
}
.question-option {
  display: flex;
  align-items: center;
  gap: 10px;
  text-align: left;
  padding: 10px 8px;
  border: 1px solid transparent;
  border-radius: 9px;
  background: transparent;
  color: #26282e;
  cursor: pointer;
  font: inherit;
  font-size: 14px;
  line-height: 1.6;
}
.question-option:hover {
  background: #f6f7f8;
}
.question-option.selected {
  background: #f0f4fb;
  border-color: #d7e2f5;
}
.question-option > .ri-check-line {
  margin-left: auto;
  color: #507bce;
}
.option-number {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 24px;
  flex-shrink: 0;
  border-radius: 4px;
  background: #eceef2;
  color: #737985;
  font-size: 12px;
}
.custom-option {
  color: #9299a6;
}
:deep(.el-textarea__inner) {
  border-radius: 13px;
  background: #f5f6f7;
  box-shadow: 0 0 0 1px #d5d6da inset;
  padding: 14px;
  resize: none;
  font-size: 15px;
}
.question-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 18px;
  padding: 0 !important;
}
nav,
.question-buttons {
  display: flex;
  align-items: center;
  gap: 8px;
}
nav span {
  color: #686e78;
  font-size: 14px;
  font-weight: 600;
  min-width: 45px;
  text-align: center;
}
.question-buttons .el-button {
  border-radius: 11px;
  height: 36px;
  margin: 0;
}
.question-next {
  background: #303238;
  color: white;
  border-color: #303238;
}
.question-next.is-disabled {
  background: #a3a3a5;
  color: white;
  border-color: #a3a3a5;
}
.saved-note {
  color: #878d97;
  font-size: 12px;
}
@media (max-width: 600px) {
  .question-panel {
    padding: 14px;
    border-radius: 18px;
  }
}
</style>
