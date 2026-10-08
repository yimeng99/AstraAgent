import { defineComponent, h } from "vue";

// 适配 Element Plus 的 icon 属性，按钮仍负责可访问名称和交互。
function icon(name: string) {
  return defineComponent({
    name: `Remix${name.replaceAll("-", "")}`,
    setup: () => () => h("i", { class: `remix-icon ri-${name}`, "aria-hidden": "true" }),
  });
}

export const Plus = icon("add-line");
export const Search = icon("search-line");
export const Delete = icon("delete-bin-line");
export const Paperclip = icon("attachment-2");
export const Top = icon("arrow-up-line");
export const Close = icon("close-line");
export const Refresh = icon("refresh-line");
export const CopyDocument = icon("file-copy-line");
export const File = icon("file-text-line");
export const Stop = icon("stop-fill");
