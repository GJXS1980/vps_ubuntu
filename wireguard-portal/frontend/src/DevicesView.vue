<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from "vue";
import { useRoute } from "vue-router";
import { api, useSession, when, statuses } from "./session";
interface Device {
  id: string;
  label: string;
  status: string;
  metrics: string;
  last_download: number | null;
  server_name: string;
  address: string;
  fingerprint: string;
}
const s = useSession(),
  id = useRoute().params.id,
  list = ref<Device[]>([]),
  servers = ref<{ id: number; name: string }[]>([]),
  label = ref(""),
  server = ref<number>(),
  busy = ref(false),
  qr = ref("");
const selected = computed(() => list.value.find((d) => d.id === id)),
  metrics = computed(() => JSON.parse(selected.value?.metrics || "{}"));
const active = computed(() => list.value.filter((d) => d.status !== "retired")),
  enabled = computed(() => active.value.filter((d) => d.status === "enabled"));
const online = computed(
  () =>
    enabled.value.filter((d) => JSON.parse(d.metrics).status === "online")
      .length,
);
async function refresh() {
  list.value = (await api.get("/devices")).data;
  servers.value = (await api.get("/servers")).data;
  server.value ??= servers.value[0]?.id;
}
onMounted(refresh);
function clear() {
  if (qr.value) URL.revokeObjectURL(qr.value);
  qr.value = "";
}
onBeforeUnmount(clear);
function copyAddress(text: string) {
  navigator.clipboard.writeText(text);
}
let requestKey = "";
let lastRequest = "";
async function add() {
  busy.value = true;
  try {
    const signature = JSON.stringify([label.value, server.value]);
    if (!requestKey || signature !== lastRequest) {
      requestKey = crypto.randomUUID().replaceAll("-", "");
      lastRequest = signature;
    }
    await api.post(
      "/devices",
      { label: label.value, server: server.value },
      { headers: { "Idempotency-Key": requestKey } },
    );
    requestKey = "";
    label.value = "";
    await refresh();
  } finally {
    busy.value = false;
  }
}
async function take(d: Device, mode: string, kind: string) {
  busy.value = true;
  clear();
  try {
    const res = await api.post(
      "/devices/" + d.id + "/" + mode + "/" + kind,
      { code: d.fingerprint },
      { responseType: "blob" },
    );
    const url = URL.createObjectURL(res.data);
    if (kind === "qr") qr.value = url;
    else {
      const a = document.createElement("a");
      a.href = url;
      a.download = "wg-" + mode + ".conf";
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
    await refresh();
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <section v-loading="busy">
    <h1>{{ id ? "设备详情" : "我的设备" }}</h1>
    <button @click="refresh">刷新状态</button>
    <div v-if="!id" class="stats">
      <article>账号<strong>已激活</strong></article>
      <article>
        设备配额<strong>{{ active.length }} / {{ s.me?.quota }}</strong>
      </article>
      <article>
        在线 / 已启用<strong>{{ online }} / {{ enabled.length }}</strong>
      </article>
      <article>
        最近领取<strong>{{
          when(Math.max(0, ...list.map((d) => d.last_download || 0)))
        }}</strong>
      </article>
    </div>
    <template v-if="!id"
      ><form class="card" @submit.prevent="add">
        <h2>申请设备</h2>
        <label>设备名称<input required maxlength="40" v-model="label" /></label
        ><label
          >所属 VPS<select v-model="server" required>
            <option v-for="v in servers" :key="v.id" :value="v.id">
              {{ v.name }}
            </option>
          </select></label
        ><button :disabled="!server">提交申请</button>
      </form>
      <article v-for="d in list" :key="d.id">
        <router-link :to="'/devices/' + d.id">{{ d.label }}</router-link> ·
        {{ statuses[d.status] }} · {{ d.server_name }}
      </article>
      <el-empty v-if="!list.length" description="暂无设备"
    /></template>
    <article v-else-if="selected">
      <h2>{{ selected.label }}</h2>
      <p>
        {{ selected.server_name }} · {{ statuses[selected.status] }} ·
        {{ selected.address }}
      </p>
      <button v-if="selected.address" @click="copyAddress(selected.address)">
        复制分配地址
      </button>
      <p>
        采样 {{ when(metrics.sampled) }} · 最近握手
        {{ metrics.age == null ? "未知" : when(metrics.sampled - metrics.age) }}
        · 接收 {{ metrics.rx ?? "—" }} B · 发送 {{ metrics.tx ?? "—" }} B
      </p>
      <p>最近领取 {{ when(selected.last_download) }}</p>
      <p>
        二维码和 .conf 文件包含 VPN 凭据，请勿分享。安装 WireGuard
        后选择导入文件或扫描二维码，每次只启用一种模式。
      </p>
      <p>
        global 将默认流量送入隧道。proxy 需在指定应用中设置 SOCKS5 代理
        10.66.77.1:1080。
      </p>
      <div v-for="mode in ['global', 'proxy']" :key="mode">
        <strong>{{ mode }}</strong>
        <button
          :disabled="selected.status !== 'enabled'"
          @click="take(selected, mode, 'conf')"
        >
          下载配置</button
        ><button
          :disabled="selected.status !== 'enabled'"
          @click="take(selected, mode, 'qr')"
        >
          显示二维码
        </button>
      </div>
      <div v-if="qr">
        <img :src="qr" alt="本设备 WireGuard 配置二维码" /><button
          @click="clear"
        >
          关闭二维码
        </button>
      </div>
    </article>
    <el-empty v-else description="未找到设备" />
  </section>
</template>
