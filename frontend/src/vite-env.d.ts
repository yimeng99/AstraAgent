/// <reference types="vite/client" />

// Vite 客户端类型：声明了 `*.css` / `*.svg` 等非代码模块的导入，
// 也提供 import.meta.env 的类型。项目原先缺这个文件，
// 导致从包里导入 CSS（@js-preview/excel/lib/index.css）会报 TS2307。
