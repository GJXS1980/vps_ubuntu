<script setup lang="ts">
import { reactive, ref, computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { api, useSession } from "./session";
const s = useSession(),
  r = useRouter(),
  page = String(useRoute().params.page);
const f = reactive({
    username: "",
    password: "",
    email: "",
    otp: "",
    code: "",
    invite: "",
    old: "",
  }),
  busy = ref(false);
const titles: Record<string, string> = {
  login: "登录",
  register: "注册账号",
  forgot: "找回密码",
  pending: "等待管理员审核",
  security: "个人与安全",
};
const title = computed(() => titles[page]);
async function submit(action: string) {
  busy.value = true;
  try {
    if (action === "login") {
      await api.post("/login", {
        username: f.username,
        password: f.password,
        otp: f.otp,
      });
      await s.refresh();
      r.push("/devices");
    }
    if (action === "register") {
      const { data } = await api.post("/register", {
        username: f.username,
        password: f.password,
        email: f.email,
        invite: f.invite,
      });
      ElMessage.success(data.message);
      r.push(data.status === "pending" ? "/account/pending" : "/account/login");
    }
    if (action === "forgot") {
      ElMessage.success(
        (await api.post("/forgot", { email: f.email })).data.message,
      );
    }
    if (action === "reset") {
      await api.post("/reset", { code: f.code, password: f.password });
      r.push("/account/login");
    }
    if (action === "password") {
      await api.post("/password", { old: f.old, password: f.password });
      s.me = null;
      r.push("/account/login");
    }
    if (action === "profile") {
      await api.post("/profile", { email: f.email });
      await s.refresh();
      ElMessage.success("邮箱已更新，请重新验证");
    }
    if (action === "verify") {
      await api.post("/verify", { code: f.code });
      await s.refresh();
      ElMessage.success("邮箱已验证");
    }
    if (action === "verification") {
      await api.post("/verification");
      ElMessage.success("验证码已发送");
    }
    if (action === "revoke-sessions") {
      await ElMessageBox.confirm("撤销此账号的全部登录会话？");
      await api.post("/revoke-sessions");
      s.me = null;
      r.push("/account/login");
    }
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <section class="card narrow" v-loading="busy">
    <h1>{{ title }}</h1>
    <p v-if="page === 'pending'">管理员批准后，请返回登录页。</p>
    <form
      v-if="['login', 'register'].includes(page)"
      @submit.prevent="submit(page)"
    >
      <label
        >用户名<input
          v-model="f.username"
          required
          minlength="2"
          maxlength="40"
          autocomplete="username"
      /></label>
      <label v-if="page === 'register'"
        >邮箱<input v-model="f.email" type="email" required
      /></label>
      <label
        >密码<input
          v-model="f.password"
          type="password"
          required
          :minlength="page === 'register' ? 12 : 1"
          maxlength="128"
      /></label>
      <label v-if="page === 'register'"
        >邀请码（按需填写）<input v-model="f.invite" /></label
      ><label v-else
        >管理员动态验证码<input
          v-model="f.otp"
          inputmode="numeric"
          maxlength="6" /></label
      ><button>{{ title }}</button>
    </form>
    <template v-if="page === 'forgot'"
      ><form @submit.prevent="submit('forgot')">
        <label
          >已验证邮箱<input v-model="f.email" type="email" required /></label
        ><button>获取重置码</button>
      </form>
      <form @submit.prevent="submit('reset')">
        <label>重置码<input v-model="f.code" required /></label
        ><label
          >新密码<input
            v-model="f.password"
            type="password"
            required
            minlength="12" /></label
        ><button>重置密码</button>
      </form></template
    >
    <template v-if="page === 'security' && s.me"
      ><p>{{ s.me.email }} · {{ s.me.verified ? "已验证" : "待验证" }}</p>
      <form @submit.prevent="submit('profile')">
        <label>修改邮箱<input type="email" required v-model="f.email" /></label
        ><button>保存邮箱</button>
      </form>
      <button @click="submit('verification')">发送邮箱验证码</button>
      <form @submit.prevent="submit('verify')">
        <label>验证码<input v-model="f.code" required /></label
        ><button>确认邮箱</button>
      </form>
      <form @submit.prevent="submit('password')">
        <label>当前密码<input v-model="f.old" type="password" required /></label
        ><label
          >新密码<input
            v-model="f.password"
            type="password"
            minlength="12"
            required /></label
        ><button>修改密码</button>
      </form>
      <button @click="submit('revoke-sessions')">撤销全部会话</button></template
    >
    <footer v-else>
      <router-link
        v-for="p in ['login', 'register', 'forgot'].filter((p) => p !== page)"
        :key="p"
        :to="'/account/' + p"
        >{{ titles[p] }}</router-link
      >
    </footer>
  </section>
</template>
