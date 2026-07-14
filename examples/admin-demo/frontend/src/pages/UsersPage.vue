<script setup lang="ts">
import { Search, UserPlus } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { api, type User } from "../api";
import StatePanel from "../components/StatePanel.vue";

const users = ref<User[]>([]);
const query = ref("");
const loading = ref(true);
const error = ref("");
const filteredUsers = computed(() => {
  const value = query.value.trim().toLowerCase();
  return value ? users.value.filter((user) => `${user.name} ${user.email}`.toLowerCase().includes(value)) : users.value;
});

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try { users.value = await api.getUsers(); }
  catch (cause) { console.error("Failed to load users", cause); error.value = cause instanceof Error ? cause.message : "未知错误"; }
  finally { loading.value = false; }
}

onMounted(load);
</script>

<template>
  <section>
    <div class="page-heading"><div><span class="eyebrow">成员与权限</span><h1>用户管理</h1><p>查看平台成员及其账号状态。</p></div><button class="primary-button"><UserPlus :size="17" />添加用户</button></div>
    <StatePanel :loading="loading" :error="error" @retry="load">
      <section class="content-section">
        <div class="table-toolbar"><label class="search-field"><Search :size="17" /><input v-model="query" type="search" placeholder="搜索姓名或邮箱" aria-label="搜索用户" /></label><span>共 {{ filteredUsers.length }} 位用户</span></div>
        <div class="table-scroll">
          <table><thead><tr><th>用户</th><th>角色</th><th>状态</th><th>加入时间</th></tr></thead>
            <tbody><tr v-for="user in filteredUsers" :key="user.id"><td><div class="identity"><span class="avatar">{{ user.name.slice(0, 1) }}</span><div><strong>{{ user.name }}</strong><span>{{ user.email }}</span></div></div></td><td>{{ user.role }}</td><td><span class="status" :data-status="user.status">{{ user.status === "active" ? "正常" : "停用" }}</span></td><td>{{ user.joinedAt }}</td></tr></tbody>
          </table>
        </div>
        <div v-if="filteredUsers.length === 0" class="empty-state">没有找到匹配的用户</div>
      </section>
    </StatePanel>
  </section>
</template>
