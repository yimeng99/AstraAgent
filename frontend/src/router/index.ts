import { createRouter, createWebHistory } from "vue-router";
import ChatLayout from "@/layouts/index.vue";

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: "/", name: "chat", component: ChatLayout },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});
