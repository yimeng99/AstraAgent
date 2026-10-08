import { createApp } from "vue";
import ElementPlus from "element-plus";
import "element-plus/dist/index.css";
import "remixicon/fonts/remixicon.css";
import "markstream-vue/index.css";
import "./index.scss";
import App from "./App.vue";
import { createPinia } from "pinia";
import { router } from "./router";

createApp(App).use(createPinia()).use(router).use(ElementPlus).mount("#app");
