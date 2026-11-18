<script setup lang="ts">
import { computed, ref, onMounted, reactive } from "vue";
import { useRoute } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { api, useSession, statuses, when } from "./session";
type Row = Record<string, any>;
const page = String(useRoute().params.page),
  s = useSession(),
  busy = ref(false),
  users = ref<Row[]>([]),
  devices = ref<Row[]>([]),
  servers = ref<Row[]>([]),
  logs = ref<Row[]>([]),
  peers = ref<Row[]>([]),
  selected = ref<Row>(),
  search = ref(""),
  offset = ref(1),
  group = ref("audit"),
  sid = ref(0),
  owner = ref(0),
  newName = ref(""),
  addr = ref(""),
  invite = ref(""),
  cfg = reactive({ registration: "review", quota: 1 });
const titles: Record<string, string> = {
  overview: "管理概览",
  users: "用户与审核",
  devices: "设备与 Peer",
  servers: "VPS 与在线监控",
  logs: "操作记录",
  settings: "系统设置",
};
const data = computed(() =>
  page === "users"
    ? users.value
    : page === "devices"
      ? devices.value
      : page === "servers"
        ? peers.value
        : logs.value,
);
const filtered = computed(() =>
  data.value.filter((r) =>
    Object.values(r)
      .join(" ")
      .toLowerCase()
      .includes(search.value.toLowerCase()),
  ),
);
const paged = computed(() =>
  filtered.value.slice((offset.value - 1) * 15, offset.value * 15),
);
const columns = computed(() =>
  page === "users"
    ? { username: "用户名", email: "邮箱", status: "状态", quota: "配额" }
    : page === "devices"
      ? { label: "设备", peer: "Peer", address: "地址", status: "状态" }
      : page === "servers"
        ? {
            name: "Peer",
            address: "地址",
            status: "状态",
            rx: "接收 B",
            tx: "发送 B",
          }
        : group.value === "jobs"
          ? { device: "设备", status: "状态", error: "异常", tries: "重试" }
          : group.value === "downloads"
            ? { device: "设备", user: "用户", mode: "配置", time: "时间" }
            : { actor: "操作者", action: "操作", target: "对象", time: "时间" },
);
async function refresh() {
  busy.value = true;
  try {
    if (["overview", "users", "servers"].includes(page))
      users.value = (await api.get("/admin/users")).data;
    if (["overview", "devices"].includes(page))
      devices.value = (await api.get("/admin/devices")).data;
    if (page === "servers") {
      servers.value = (await api.get("/servers")).data;
      sid.value ||= servers.value[0]?.id;
    }
    if (page === "logs")
      logs.value = (await api.get("/admin/logs")).data[group.value];
    if (page === "settings") {
      const v = (await api.get("/admin/settings")).data;
      Object.assign(cfg, v, { quota: Number(v.quota) });
    }
  } finally {
    busy.value = false;
  }
}
onMounted(refresh);
async function inspect() {
  busy.value = true;
  try {
    peers.value = (
      await api.get("/admin/servers/" + sid.value + "/peers")
    ).data.rows;
    selected.value = undefined;
  } finally {
    busy.value = false;
  }
}
async function mutate(path: string, body: unknown, msg: string) {
  await ElMessageBox.confirm(msg, "确认操作");
  busy.value = true;
  try {
    await api.post(path, body);
    selected.value = undefined;
    ElMessage.success("操作已提交");
    await refresh();
  } finally {
    busy.value = false;
  }
}
function account(status: string) {
  if (selected.value)
    mutate(
      "/admin/users/" + selected.value.id,
      { status, quota: selected.value.quota },
      "保存账号状态与设备配额？",
    );
}
async function invitation() {
  invite.value = (await api.post("/admin/invite")).data.code;
}
const restoreFile = ref<File>(),
  restoreOtp = ref("");
function pick(e: Event) {
  restoreFile.value = (e.target as HTMLInputElement).files?.[0];
}
async function restore() {
  if (!restoreFile.value) return;
  await ElMessageBox.confirm(
    "确认用备份替换全部用户和设备关系？当前会话将撤销。",
    "恢复数据库",
  );
  await api.post("/admin/restore", restoreFile.value, {
    headers: {
      "Content-Type": "application/octet-stream",
      "X-Confirm-Restore": "RESTORE",
      "X-Admin-OTP": restoreOtp.value,
    },
  });
  location.hash = "/account/login";
  location.reload();
}
async function backup() {
  const r = await api.post("/admin/backup", {}, { responseType: "blob" });
  const u = URL.createObjectURL(r.data);
  const a = document.createElement("a");
  a.href = u;
  a.download = "portal-backup.enc";
  a.click();
  setTimeout(() => URL.revokeObjectURL(u), 1000);
}
</script>
<template>
  <section v-loading="busy">
    <h1>{{ titles[page] }}</h1>
    <div class="stats" v-if="page === 'overview'">
      <article>
        注册用户<strong>{{ users.length }}</strong>
      </article>
      <article>
        待审核<strong>{{
          users.filter((u) => u.status === "pending").length
        }}</strong>
      </article>
      <article>
        设备<strong>{{ devices.length }}</strong>
      </article>
    </div>
    <template v-if="page === 'settings'"
      ><form
        class="card"
        @submit.prevent="mutate('/admin/settings', cfg, '保存注册策略？')"
      >
        <label
          >注册模式<select v-model="cfg.registration">
            <option
              v-for="(v, k) in {
                review: '公开注册，人工审核',
                closed: '关闭注册',
                invite: '邀请注册',
                auto: '自动激活',
              }"
              :value="k"
              :key="k"
            >
              {{ v }}
            </option>
          </select></label
        ><label
          >新用户设备配额<input
            type="number"
            min="1"
            max="253"
            v-model.number="cfg.quota"
            required /></label
        ><button>保存设置</button>
      </form>
      <article>
        <button @click="invitation">生成一次性邀请码</button> {{ invite }}
      </article>
      <article>
        <h2>备份与恢复</h2>
        <button @click="backup">下载加密备份</button>
        <p>
          恢复会替换账号与绑定关系。相同版本和管理员 MFA
          可直接恢复；跨机器恢复请使用本地控制台。
        </p>
        <form @submit.prevent="restore">
          <label
            >选择加密备份<input
              required
              type="file"
              accept=".enc"
              @change="pick" /></label
          ><label
            >管理员动态验证码<input
              required
              v-model="restoreOtp"
              maxlength="6" /></label
          ><button>恢复备份</button>
        </form>
      </article></template
    >
    <template v-if="page === 'servers'"
      ><form
        v-if="s.me?.role === 'super_admin'"
        class="card"
        @submit.prevent="
          mutate(
            '/admin/servers',
            { name: newName, address: addr },
            '添加管理节点？',
          )
        "
      >
        <label>节点名称<input required v-model="newName" /></label
        ><label>隧道 IPv4<input required v-model="addr" /></label
        ><button>添加 VPS</button>
      </form>
      <label
        >查看节点<select v-model="sid">
          <option v-for="v in servers" :value="v.id" :key="v.id">
            {{ v.name }} · {{ v.health }} · {{ when(v.checked) }}
          </option>
        </select></label
      ><button :disabled="!sid" @click="inspect">读取实时状态</button></template
    >
    <template v-if="!['settings', 'overview'].includes(page)"
      ><div v-if="page === 'logs'">
        <select v-model="group" @change="refresh">
          <option value="audit">操作审计</option>
          <option value="jobs">任务异常与重试</option>
          <option value="downloads">配置领取</option>
        </select>
      </div>
      <button
        v-if="page === 'devices'"
        @click="mutate('/admin/sync', {}, '重新同步所有 VPS？')"
      >
        立即对账</button
      ><label>搜索<input v-model="search" @input="offset = 1" /></label
      ><el-table
        :data="paged"
        empty-text="暂无记录"
        @row-click="(r: Row) => (selected = { ...r })"
        ><el-table-column
          v-for="(v, k) in columns"
          :key="k"
          :label="v"
          min-width="110"
          ><template #default="scope">{{
            k === "status"
              ? statuses[scope.row[k]] || scope.row[k]
              : k === "time"
                ? when(scope.row[k])
                : scope.row[k]
          }}</template></el-table-column
        ></el-table
      ><el-pagination
        v-model:current-page="offset"
        :page-size="15"
        :total="filtered.length"
        layout="prev,pager,next"
      />
      <article v-if="selected">
        <h2>
          {{
            selected.username || selected.label || selected.name || "记录详情"
          }}
        </h2>
        <dl>
          <template v-for="(value, key) in selected" :key="key"
            ><dt>{{ key }}</dt>
            <dd>{{ value }}</dd></template
          >
        </dl>
        <template v-if="page === 'users' && selected.role === 'user'"
          ><label
            >设备配额<input
              type="number"
              min="1"
              max="253"
              v-model.number="selected.quota" /></label
          ><button @click="account('active')">批准 / 恢复</button
          ><button @click="account('disabled')">停用账号</button></template
        >
        <button
          v-if="
            page === 'logs' && group === 'jobs' && selected.status !== 'done'
          "
          @click="
            mutate(
              '/admin/jobs/' + selected.id + '/retry',
              {},
              '核对远端后重试任务？',
            )
          "
        >
          重新同步任务</button
        ><template v-if="page === 'devices'"
          ><button
            v-for="(v, k) in {
              enable: '启用',
              disable: '停用',
              rotate: '轮换密钥',
              delete: '回收设备',
            }"
            :key="k"
            @click="
              mutate(
                '/admin/devices/' + selected.id + '/' + k,
                {},
                v + '所选设备？',
              )
            "
          >
            {{ v }}
          </button></template
        ><template v-if="page === 'servers' && !selected.device"
          ><p>外部管理资源</p>
          <template v-if="s.me?.role === 'super_admin'"
            ><label
              >绑定到用户<select v-model="owner">
                <option
                  v-for="u in users.filter((u) => u.status === 'active')"
                  :value="u.id"
                  :key="u.id"
                >
                  {{ u.username }}
                </option>
              </select></label
            ><button
              :disabled="!owner"
              @click="
                mutate(
                  '/admin/adopt',
                  {
                    server: sid,
                    user: owner,
                    peer: selected.name,
                    label: selected.label,
                    fingerprint: selected.fingerprint,
                  },
                  '确认已获得原持有者授权，并接管此 Peer？',
                )
              "
            >
              授权绑定
            </button></template
          ></template
        >
      </article></template
    >
  </section>
</template>
