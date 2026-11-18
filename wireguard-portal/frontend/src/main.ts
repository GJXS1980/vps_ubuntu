import { createApp } from "vue";
import { createPinia } from "pinia";
import { createRouter, createWebHashHistory } from "vue-router";
import {
  ElMessage,
  ElEmpty,
  ElLoading,
  ElPagination,
  ElTable,
  ElTableColumn,
} from "element-plus";
import { ApiFailure } from "./session";
import "element-plus/dist/index.css";
import App from "./App.vue";
import AccountView from "./AccountView.vue";
import DevicesView from "./DevicesView.vue";
import AdminView from "./AdminView.vue";
import "./style.css";
const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/", redirect: "/devices" },
    { path: "/account/:page", component: AccountView },
    { path: "/devices/:id?", component: DevicesView },
    { path: "/admin/:page", component: AdminView },
  ],
});
const app = createApp(App);
app.config.errorHandler = (error) => {
  if (error instanceof ApiFailure || error === "cancel" || error === "close")
    return;
  ElMessage.error("页面操作未完成，请刷新后重试");
};
app
  .use(createPinia())
  .use(router)
  .use(ElEmpty)
  .use(ElLoading)
  .use(ElPagination)
  .use(ElTable)
  .use(ElTableColumn)
  .mount("#app");
