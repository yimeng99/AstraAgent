import { defineStore } from "pinia";
import type { Model, ModelList } from "@/components/modelSelector/types";

export const useModelsStore = defineStore("models", {
  state: () => ({
    list: null as ModelList | null,
    selected: undefined as { provider: string; model: Model } | undefined,
  }),
});
