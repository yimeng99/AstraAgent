<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from "vue";
import ChatSidebar from "@/layouts/components/chatSidebar.vue";
import ChatConversation from "@/layouts/components/chatConversation.vue";
import { useChatStore } from "@/stores/chat";
import { useUserStore } from "@/stores/user";

const chat = useChatStore();
const user = useUserStore();
const loading = ref(true);
const error = ref("");
let disposed = false;
async function initialize() {
  loading.value = true;
  error.value = "";
  try {
    await user.loadUsers();
    if (!disposed) await chat.initialize();
  } catch (issue) {
    error.value = (issue as Error).message;
  } finally {
    loading.value = false;
  }
}
onMounted(initialize);
onBeforeUnmount(() => {
  disposed = true;
});
onBeforeUnmount(() => chat.reset());
</script>

<template>
  <div v-if="loading || error" v-loading="loading" class="workspace-loading">
    <template v-if="error"
      ><p role="alert">{{ error }}</p>
      <el-button @click="initialize">重试</el-button></template
    >
  </div>
  <div v-else class="workspace">
    <ChatSidebar />
    <ChatConversation />
  </div>
</template>

<style scoped lang="scss">
.workspace-loading {
  height: 100dvh;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
}
.workspace {
  display: flex;
  height: 100dvh;
  overflow: hidden;
}
</style>
