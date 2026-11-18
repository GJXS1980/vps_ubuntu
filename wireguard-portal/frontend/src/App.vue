<script setup lang="ts">
import { onMounted, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useSession, api } from "./session";
const s = useSession(),
  route = useRoute(),
  router = useRouter();
function guard() {
  if (!s.ready) return;
  if (
    !s.me &&
    !["login", "register", "forgot", "pending"].includes(
      String(route.params.page),
    )
  )
    router.replace("/account/login");
  else if (route.path.startsWith("/admin") && s.me?.role === "user")
    router.replace("/devices");
}
onMounted(async () => {
  await s.refresh();
  guard();
});
watch(() => route.fullPath, guard);
async function logout() {
  await api.post("/logout");
  s.me = null;
  router.replace("/account/login");
}
</script>
<template>
  <header>
    <div><strong>WireGuard</strong> 用户中心</div>
    <span v-if="s.me"
      >{{ s.me.username }} · <button @click="logout">退出</button></span
    >
  </header>
  <main v-if="s.ready">
    <nav v-if="s.me">
      <router-link to="/devices">我的设备</router-link
      ><router-link to="/account/security">个人与安全</router-link
      ><template v-if="s.me.role !== 'user'"
        ><router-link
          v-for="(title, key) in {
            overview: '管理概览',
            users: '用户审核',
            devices: '设备管理',
            servers: 'VPS 监控',
            logs: '操作记录',
          }"
          :key="key"
          :to="'/admin/' + key"
          >{{ title }}</router-link
        ><router-link v-if="s.me.role === 'super_admin'" to="/admin/settings"
          >系统设置</router-link
        ></template
      >
    </nav>
    <router-view :key="route.fullPath" />
  </main>
</template>
