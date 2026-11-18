import axios from "axios";
import { defineStore } from "pinia";
import { ElMessage } from "element-plus";
export class ApiFailure extends Error {}
export const api = axios.create({ baseURL: "/api" });
export interface Me {
  id: number;
  username: string;
  email: string;
  role: string;
  status: string;
  quota: number;
  verified: number;
  csrf: string;
}
export const useSession = defineStore("session", {
  state: () => ({ me: null as Me | null, ready: false }),
  actions: {
    async refresh() {
      try {
        this.me = (
          await api.get("/me", {
            validateStatus: (s) => s === 200 || s === 401,
          })
        ).data;
        if (!this.me?.csrf) this.me = null;
      } finally {
        this.ready = true;
      }
    },
  },
});
api.interceptors.request.use((c) => {
  const csrf = useSession().me?.csrf;
  if (csrf) c.headers["X-CSRF-Token"] = csrf;
  return c;
});
api.interceptors.response.use(
  (r) => r,
  async (e) => {
    let data = e.response?.data;
    if (data instanceof Blob) {
      try {
        data = JSON.parse(await data.text());
      } catch {
        data = null;
      }
    }
    ElMessage.error(data?.detail || "连接失败，请检查服务状态");
    if (e.response?.status === 401 && e.config?.url !== "/login") {
      useSession().me = null;
      location.hash = "/account/login";
    }
    return Promise.reject(new ApiFailure("请求未完成"));
  },
);
export function when(t: number | null) {
  return t ? new Date(t * 1000).toLocaleString() : "暂无";
}
export const statuses: Record<string, string> = {
  enabled: "已启用",
  disabled: "已停用",
  pending: "等待处理",
  missing: "远端缺失",
  retired: "已回收",
  error: "操作异常",
  active: "已激活",
  online: "在线",
  offline: "离线",
  never: "尚未连接",
  unknown: "未知",
};
