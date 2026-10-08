<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { requestApi } from "@/utils/request";
import { useModelsStore } from "@/stores/models.ts";
import type { Model, Provider, ModelList } from "./types";

defineProps<{ disabled?: boolean }>();
const models = useModelsStore();
const { selected } = storeToRefs(models);
const open = ref(false);
const query = ref("");
const providers = computed(() => models.list?.providers ?? []);
const defaultModel = computed(() => models.list?.default);
const loading = ref(false);
const error = ref("");
const filtered = computed(() => {
  const term = query.value.trim().toLowerCase();
  return providers.value
    .map((provider) => ({
      ...provider,
      children: provider.children.filter((model) =>
        `${provider.name} ${model.name} ${model.id}`.toLowerCase().includes(term),
      ),
    }))
    .filter((provider) => provider.children.length);
});
onMounted(async () => {
  loading.value = true;
  try {
    models.list = await requestApi<ModelList>({ url: "/models" });
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "模型加载失败";
  } finally {
    loading.value = false;
  }
});
function choose(provider: Provider, model: Model) {
  selected.value = { provider: provider.id, model };
  open.value = false;
}
</script>

<template>
  <el-popover
    v-model:visible="open"
    trigger="click"
    placement="top-end"
    :width="240"
    :show-arrow="false"
    :disabled="disabled"
    popper-class="model-picker-popover"
    @show="query = ''"
  >
    <template #reference>
      <button
        class="model-trigger"
        type="button"
        :disabled="disabled"
        :aria-expanded="open"
        aria-label="选择模型"
      >
        <span>{{ selected?.model.name ?? defaultModel?.name ?? "选择模型" }}</span>
        <i :class="open ? 'ri-arrow-up-s-line' : 'ri-arrow-down-s-line'" aria-hidden="true" />
      </button>
    </template>
    <div class="model-picker">
      <input v-model="query" class="model-search" placeholder="搜索模型…" aria-label="搜索模型" />
      <div class="model-options">
        <button
          v-if="defaultModel"
          type="button"
          class="model-option default-route"
          :class="{ selected: !selected }"
          :aria-pressed="!selected"
          @click="
            selected = undefined;
            open = false;
          "
        >
          <span class="default-route-label">
            {{ defaultModel.name }}
            <el-tooltip :content="defaultModel.description" placement="top">
              <i
                class="ri-question-line route-help"
                tabindex="0"
                :aria-label="defaultModel.description"
                @click.stop
                @keydown.enter.stop.prevent
                @keydown.space.stop.prevent
              />
            </el-tooltip>
          </span>
          <i v-if="!selected" class="ri-check-line" aria-hidden="true" />
        </button>
        <p v-if="loading" class="model-message" role="status">正在加载模型…</p>
        <div v-else-if="error" class="model-message" role="alert">
          {{ error }}
        </div>
        <p v-else-if="!filtered.length" class="model-message">
          {{ providers.length ? "没有匹配的模型" : "暂无可用模型" }}
        </p>
        <section v-for="provider in filtered" :key="provider.id" :aria-label="provider.name">
          <h3>{{ provider.name }}</h3>
          <button
            v-for="model in provider.children"
            :key="model.id"
            type="button"
            class="model-option"
            :class="{
              selected: selected?.provider === provider.id && selected.model.id === model.id,
            }"
            :aria-pressed="selected?.provider === provider.id && selected.model.id === model.id"
            @click="choose(provider, model)"
          >
            <span>{{ model.name }}</span>
            <i
              v-if="selected?.provider === provider.id && selected.model.id === model.id"
              class="ri-check-line"
              aria-hidden="true"
            />
          </button>
        </section>
      </div>
    </div>
  </el-popover>
</template>

<style scoped>
.model-trigger {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
  max-width: 200px;
  padding: 6px 0;
  border: 0;
  background: transparent;
  color: #858991;
  cursor: pointer;
  font: inherit;
  font-size: 13px;
}
.model-trigger span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.model-trigger:disabled {
  opacity: 0.5;
  cursor: default;
}
.model-search {
  box-sizing: border-box;
  width: 100%;
  padding: 8px;
  border: 0;
  background: transparent;
  color: #25272c;
  font: inherit;
  font-size: 12px;
  line-height: 20px;
  outline: none;
}
.model-search::placeholder {
  color: #a0a4ac;
}
.model-options {
  max-height: min(300px, 50vh);
  overflow-y: auto;
  scrollbar-width: thin;
}
h3 {
  margin: 6px 8px 2px;
  font-size: 10px;
  line-height: 14px;
  font-weight: 500;
  color: #989da5;
}
.model-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  padding: 7px 8px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: #25272c;
  font: inherit;
  font-size: 13px;
  line-height: 20px;
  text-align: left;
  cursor: pointer;
}
.model-option span {
  overflow-wrap: anywhere;
}
.default-route {
  margin-bottom: 4px;
}
.default-route-label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.route-help {
  color: #989da5;
  font-size: 13px;
  cursor: help;
}
.route-help:focus-visible {
  outline: 2px solid #a9c1fa;
  border-radius: 50%;
}
.model-option:hover,
.model-option.selected {
  background: #eceeef;
}
.model-option:focus-visible,
.model-trigger:focus-visible {
  outline: 2px solid #a9c1fa;
  outline-offset: -2px;
}
.model-message {
  padding: 8px;
  color: #858991;
  font-size: 13px;
}
@media (max-width: 600px) {
  .model-trigger {
    max-width: 140px;
  }
}
</style>
<style>
.el-popover.model-picker-popover {
  padding: 6px;
  border-radius: 12px;
  max-width: calc(100vw - 24px);
  box-sizing: border-box;
  background: #fff;
  border-color: #eceef1;
  box-shadow: 0 6px 24px #18243b0d;
}
</style>
