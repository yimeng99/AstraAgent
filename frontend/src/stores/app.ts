import { defineStore } from "pinia";

export const useAppStore = defineStore("app", {
  state: () => ({
    appName: "CommonAgent",
    agentTeamLabel: "智能体团队",
    footerText: "AI 也会犯错请仔细甄别",
  }),
});
