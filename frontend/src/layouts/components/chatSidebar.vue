<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onBeforeUnmount } from "vue";
import { storeToRefs } from "pinia";
import { useAppStore } from "@/stores/app";
import { ElMessage, ElMessageBox, type InputInstance } from "element-plus";
import { Search } from "@/components/icons";
import brandMark from "@/assets/astra-mark.svg";
import { useChatStore } from "@/stores/chat";
import UserMenu from "@/components/userMenu.vue";

const chat = useChatStore();
const { appName } = storeToRefs(useAppStore());
const { threads, threadId, loading, threadsError, busy, navigationDisabled } = storeToRefs(chat);
const search = ref("");
const searchOpen = ref(false);
const searchInput = ref<InputInstance>();
const refreshing = ref(false);
async function refreshHistory() {
  if (refreshing.value) return;
  refreshing.value = true;
  try {
    if (await chat.refreshCurrent()) ElMessage.success("会话已刷新");
  } finally {
    refreshing.value = false;
  }
}
function searchShortcut(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    if (!event.repeat) void toggleSearch();
  }
}
onMounted(() => window.addEventListener("keydown", searchShortcut));
onBeforeUnmount(() => window.removeEventListener("keydown", searchShortcut));
async function toggleSearch() {
  searchOpen.value = !searchOpen.value;
  if (searchOpen.value) {
    await nextTick();
    searchInput.value?.focus();
  } else search.value = "";
}
const openThreadMenu = ref<string | null>(null);
const dialogOpen = ref(false);
const filteredThreads = computed(() =>
  threads.value.filter((thread) =>
    (thread.title || "新会话").toLowerCase().includes(search.value.toLowerCase()),
  ),
);

async function manageThread(command: string, id: string) {
  if (dialogOpen.value || busy.value || navigationDisabled.value) return;
  dialogOpen.value = true;
  try {
    if (command === "rename") {
      const { value } = await ElMessageBox.prompt("请输入会话标题", "重命名会话", {
        inputValue: threads.value.find((thread) => thread.id === id)?.title || "新会话",
        inputValidator: (value) =>
          (!!value?.trim() && value.trim().length <= 100) || "请输入 1–100 个字符",
        confirmButtonText: "保存",
        cancelButtonText: "取消",
      });
      await chat.renameThread(id, value.trim());
    } else if (command === "delete") {
      await ElMessageBox.confirm("删除后无法恢复该会话及其消息。", "删除会话", {
        type: "warning",
        confirmButtonText: "删除",
        cancelButtonText: "取消",
      });
      await chat.deleteThread(id);
    }
  } catch (issue) {
    if (issue !== "cancel" && issue !== "close") ElMessage.error((issue as Error).message);
  } finally {
    dialogOpen.value = false;
  }
}
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
      <img class="brand-symbol" :src="brandMark" alt="" />
      <strong>{{ appName }}</strong>
    </div>
    <el-button
      class="new-chat"
      :disabled="navigationDisabled || dialogOpen"
      @click="chat.newThread()"
    >
      <i class="ri-chat-new-line" aria-hidden="true" />新会话
    </el-button>
    <div class="history-heading">
      <span>会话历史</span>
      <div class="history-actions">
        <el-tooltip
          placement="bottom"
          :show-after="250"
          :show-arrow="false"
          :offset="9"
          popper-class="sidebar-action-tooltip"
        >
          <template #content
            ><span class="shortcut-tip">搜索 <kbd>Ctrl + K</kbd></span></template
          >
          <button
            class="history-action"
            :class="{ active: searchOpen }"
            aria-label="搜索会话"
            aria-keyshortcuts="Control+k Meta+k"
            :aria-expanded="searchOpen"
            @click="toggleSearch"
          >
            <i class="ri-search-line" aria-hidden="true" />
          </button>
        </el-tooltip>
        <el-tooltip
          content="刷新会话"
          placement="bottom"
          :show-after="250"
          :show-arrow="false"
          :offset="9"
          popper-class="sidebar-action-tooltip"
        >
          <button
            class="history-action"
            aria-label="刷新会话"
            :disabled="loading || refreshing || navigationDisabled || busy"
            :aria-busy="loading || refreshing"
            @click="refreshHistory"
          >
            <i
              class="ri-refresh-line"
              :class="{ 'is-loading': loading || refreshing }"
              aria-hidden="true"
            />
          </button>
        </el-tooltip>
      </div>
    </div>
    <el-input
      v-if="searchOpen"
      ref="searchInput"
      v-model="search"
      :prefix-icon="Search"
      placeholder="搜索会话"
      clearable
      @keydown.esc="toggleSearch"
    />
    <el-scrollbar class="thread-scroll hover-scroll">
      <nav class="thread-list" aria-label="会话历史">
        <div
          v-for="thread in filteredThreads"
          :key="thread.id"
          class="thread-row"
          :class="{ selected: threadId === thread.id, 'menu-open': openThreadMenu === thread.id }"
        >
          <button
            class="thread-select"
            :title="thread.title || '新会话'"
            :aria-current="threadId === thread.id ? 'page' : undefined"
            :disabled="navigationDisabled || dialogOpen"
            @click="chat.selectThread(thread.id)"
          >
            {{ thread.title || "新会话" }}
          </button>
          <el-dropdown
            trigger="click"
            :disabled="busy || navigationDisabled || dialogOpen"
            @command="manageThread($event, thread.id)"
            @visible-change="
              (visible: boolean) => {
                if (visible) openThreadMenu = thread.id;
                else if (openThreadMenu === thread.id) openThreadMenu = null;
              }
            "
          >
            <button class="thread-menu" aria-label="会话操作">
              <i class="ri-more-fill" aria-hidden="true" />
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="rename"
                  ><i class="ri-edit-line" aria-hidden="true" />重命名</el-dropdown-item
                >
                <el-dropdown-item command="delete"
                  ><i class="ri-delete-bin-line" aria-hidden="true" />删除</el-dropdown-item
                >
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
        <p v-if="!filteredThreads.length && !loading" class="muted empty-history">
          {{ search ? "没有找到相关会话" : "暂无会话" }}
        </p>
        <p v-if="threadsError" class="error">{{ threadsError }}</p>
      </nav>
    </el-scrollbar>
    <UserMenu />
  </aside>
</template>

<style scoped lang="scss">
.sidebar {
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  width: 264px;
  padding: 20px 12px 14px;
  gap: 8px;
  background: #f8f9fa;
  border-right: 1px solid #f0f1f2;
  :deep(.el-input__wrapper) {
    min-height: 34px;
    padding: 0 10px;
    border-radius: 6px;
    box-shadow: none;
    background: transparent;
    &:hover {
      background: #edeff1;
    }
    &.is-focus {
      background: #fff;
      box-shadow: 0 0 0 1px #c9cdd3;
    }
    .el-input__inner {
      font-size: 13px;
    }
  }
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0 6px 14px;
  height: 30px;
  color: #191c21;
  .brand-symbol {
    width: 28px;
    height: 28px;
    flex-shrink: 0;
  }
  strong {
    color: #25282e;
    font-size: 22px;
    letter-spacing: -0.7px;
    font-weight: 650;
  }
}
.new-chat.el-button {
  width: 100%;
  margin: 0;
  padding: 0 12px;
  background: #fff;
  &:hover:not(:disabled) {
    border-color: #c9cdd3;
    background: #f1f2f4;
  }
  height: 40px;
  justify-content: center;
  border-radius: 10px;
  border-color: #dddfe3;
  font-size: 14px;
  font-weight: 400;
  color: #23272e;
  i {
    font-size: 17px;
    margin-right: 7px;
  }
}
.history-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 4px 5px 0;
  font-size: 12px;
  color: #858b95;
}
.history-actions {
  display: flex;
  align-items: center;
  gap: 3px;
}
.history-action {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: #656c75;
  transition: background-color 0.15s;
  i {
    font-size: 15px;
    line-height: 1;
  }
  &:hover:not(:disabled),
  &.active {
    background: #edeef0;
  }
  &:focus-visible {
    outline: 2px solid #adb7c5;
    outline-offset: 2px;
  }
  &:disabled {
    opacity: 0.4;
  }
}
.shortcut-tip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  line-height: 20px;
  kbd {
    padding: 0 5px;
    border-radius: 3px;
    background: #626262;
    font-family: inherit;
    font-size: 11px;
    font-weight: 600;
    line-height: 18px;
    white-space: nowrap;
  }
}
// Tooltip 传送到 body，使用专属类限定样式，避免影响其他提示。
:global(.el-popper.sidebar-action-tooltip) {
  padding: 5px 8px;
  border: 0;
  border-radius: 6px;
  background: #303030;
  color: #fff;
}
.thread-scroll {
  flex: 1;
  min-height: 0;
}
.thread-menu {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  margin-right: 5px;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: #7b8798;
  opacity: 0;
  cursor: pointer;
  &:hover {
    background: #dde0e4;
  }
}
.thread-list {
  padding-right: 3px;
}
.thread-row {
  display: flex;
  align-items: center;
  &:hover {
    background: #eff0f2;
  }
  &:hover .thread-menu,
  &:focus-within .thread-menu,
  &.menu-open .thread-menu {
    opacity: 1;
  }
  border-radius: 9px;
  min-height: 36px;
  margin-bottom: 3px;
  transition: background-color 0.15s;
  &.selected {
    background: #eceef0;
    .thread-select {
      color: #22262d;
      font-weight: 500;
    }
  }
}
.thread-select {
  border: 0;
  background: transparent;
  line-height: 20px;
  text-align: left;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 8px 12px;
  color: #313740;
  font-size: 13px;
  font-weight: 400;
  &:focus-visible {
    outline: 2px solid #adb7c5;
    outline-offset: -2px;
    border-radius: 8px;
  }
}
.empty-history {
  padding: 8px;
}
@media (max-width: 760px) {
  .sidebar {
    width: 190px;
    padding: 16px 10px 12px;
  }
  .brand strong {
    font-size: 18px;
  }
}
@media (max-width: 520px) {
  .history-heading {
    flex-wrap: wrap;
    gap: 4px;
  }
  .sidebar {
    width: 144px;
  }
  .brand {
    gap: 6px;
    margin-left: 2px;
  }
  .brand .brand-symbol {
    width: 20px;
    height: 20px;
  }
  .brand strong {
    font-size: 14px;
  }
  .thread-select {
    padding-left: 8px;
    padding-right: 6px;
    padding-top: 10px;
    padding-bottom: 10px;
    font-size: 12px;
  }
}
</style>
