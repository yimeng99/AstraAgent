<script setup lang="ts">
import { computed, ref } from "vue";
import { storeToRefs } from "pinia";
import { useUserStore } from "@/stores/user";
import { useChatStore } from "@/stores/chat";

const user = useUserStore();
const chat = useChatStore();
const { currentUser, mockUserList } = storeToRefs(user);
const menuOpen = ref(false);
const detailsOpen = ref(false);
const usersOpen = ref(false);
const changing = ref(false);
const disabled = computed(
  () => chat.navigationDisabled || chat.busy || chat.sending || chat.recovering || changing.value,
);

function openPanel(panel: string) {
  menuOpen.value = false;
  if (panel === "details") detailsOpen.value = true;
  else usersOpen.value = true;
}

async function switchUser(id: string) {
  if (disabled.value) return;
  if (id === currentUser.value.user_id) {
    usersOpen.value = false;
    return;
  }
  changing.value = true;
  try {
    // 先取消旧身份请求并清理会话，避免切换后旧响应回写到新用户。
    chat.reset();
    user.selectUser(id);
    usersOpen.value = false;
    await chat.initialize();
  } finally {
    changing.value = false;
  }
}
</script>

<template>
  <div class="user-menu">
    <el-popover
      v-model:visible="menuOpen"
      trigger="click"
      placement="top-start"
      :width="190"
      :show-arrow="false"
      popper-class="user-menu-popover"
    >
      <template #reference>
        <button
          class="user-trigger"
          :class="{ active: menuOpen }"
          type="button"
          aria-label="用户菜单"
          :aria-expanded="menuOpen"
        >
          <el-avatar :size="32">{{ currentUser.name.slice(0, 1) }}</el-avatar>
          <span>{{ currentUser.name }}</span>
        </button>
      </template>
      <div class="user-menu-actions">
        <button type="button" @click="openPanel('details')">
          <i class="ri-user-line" aria-hidden="true" />详情
        </button>
        <button type="button" :disabled="disabled" @click="openPanel('switch')">
          <i class="ri-user-shared-line" aria-hidden="true" />切换用户
        </button>
      </div>
    </el-popover>
    <el-dialog v-model="detailsOpen" title="用户详情" width="min(420px, calc(100vw - 32px))">
      <dl class="user-details">
        <dt>姓名</dt>
        <dd>{{ currentUser.name }}</dd>
        <dt>用户 ID</dt>
        <dd>{{ currentUser.user_id }}</dd>
        <dt>邮箱</dt>
        <dd>{{ currentUser.email || "—" }}</dd>
        <dt>电话</dt>
        <dd>{{ currentUser.phone || "—" }}</dd>
        <dt>部门</dt>
        <dd>{{ currentUser.department || "—" }}</dd>
        <dt>职位</dt>
        <dd>{{ currentUser.title || "—" }}</dd>
        <dt>角色</dt>
        <dd>{{ currentUser.roles.join("、") || "—" }}</dd>
        <dt>状态</dt>
        <dd>{{ currentUser.active ? "启用" : "停用" }}</dd>
      </dl>
    </el-dialog>
    <el-dialog v-model="usersOpen" title="切换用户" width="min(420px, calc(100vw - 32px))">
      <div class="user-options">
        <el-empty v-if="!mockUserList.length" description="暂无可选用户" :image-size="64" />
        <button
          v-for="item in mockUserList"
          :key="item.user_id"
          type="button"
          class="user-option"
          :class="{ selected: item.user_id === currentUser.user_id }"
          :disabled="disabled || !item.active"
          @click="switchUser(item.user_id)"
        >
          <el-avatar :size="34">{{ item.name.slice(0, 1) }}</el-avatar>
          <span class="user-option-info"
            >{{ item.name
            }}<small
              >{{ item.department }} · {{ item.title }}{{ item.active ? "" : "（停用）" }}</small
            ></span
          >
          <i
            v-if="item.user_id === currentUser.user_id"
            class="ri-check-line"
            aria-label="当前用户"
          />
        </button>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
.user-menu {
  padding-top: 8px;
}
.user-trigger {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: #30343b;
  cursor: pointer;
  text-align: left;
  &:hover,
  &.active {
    background: #eceef0;
  }
  span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}
.el-avatar {
  flex-shrink: 0;
  background: #e8eaed;
  color: #646b76;
  font-size: 13px;
}
.user-menu-actions {
  display: grid;
  gap: 2px;
  button {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px;
    border: 0;
    border-radius: 8px;
    background: transparent;
    color: #30343b;
    text-align: left;
    cursor: pointer;
    &:hover:not(:disabled) {
      background: #eceef0;
    }
    &:disabled {
      opacity: 0.45;
      cursor: not-allowed;
    }
  }
}
.user-details {
  display: grid;
  grid-template-columns: 80px 1fr;
  gap: 18px;
  margin: 0 0 16px;
  dt {
    color: #92969e;
  }
  dd {
    margin: 0;
    overflow-wrap: anywhere;
  }
}
.user-options {
  display: grid;
  gap: 6px;
  max-height: 360px;
  overflow-y: auto;
}
.user-option {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  border: 0;
  border-radius: 10px;
  background: transparent;
  text-align: left;
  cursor: pointer;
  &:hover,
  &.selected {
    background: #f1f4f8;
  }
  .user-option-info {
    flex: 1;
    min-width: 0;
    overflow-wrap: anywhere;
  }
  small {
    display: block;
    color: #92969e;
    margin-top: 3px;
  }
  i {
    color: var(--chat-run-color);
  }
  &:disabled {
    cursor: not-allowed;
  }
}
</style>

<style lang="scss">
.user-menu-popover.el-popover {
  padding: 6px;
  border-radius: 14px;
  box-shadow: 0 6px 24px rgb(24 39 64 / 10%);
}
</style>
