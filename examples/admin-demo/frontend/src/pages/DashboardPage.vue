<script setup lang="ts">
import { CircleDollarSign, ShoppingBag, TrendingUp, UserRoundCheck } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { api, type DashboardData } from "../api";
import StatePanel from "../components/StatePanel.vue";

const data = ref<DashboardData | null>(null);
const loading = ref(true);
const error = ref("");

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    data.value = await api.getDashboard();
  } catch (cause) {
    console.error("Failed to load dashboard", cause);
    error.value = cause instanceof Error ? cause.message : "未知错误";
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <section>
    <div class="page-heading">
      <div><span class="eyebrow">业务概览</span><h1>仪表盘</h1><p>查看团队当前的核心运营指标。</p></div>
      <span class="date-label">数据更新于今天 09:30</span>
    </div>

    <StatePanel :loading="loading" :error="error" @retry="load">
      <template v-if="data">
        <div class="metric-grid">
          <article class="metric"><span class="metric__icon metric__icon--blue"><UserRoundCheck /></span><div><span>用户总数</span><strong>{{ data.totalUsers.toLocaleString() }}</strong><small>较上月 +8.2%</small></div></article>
          <article class="metric"><span class="metric__icon metric__icon--amber"><ShoppingBag /></span><div><span>进行中订单</span><strong>{{ data.activeOrders }}</strong><small>12 个等待处理</small></div></article>
          <article class="metric"><span class="metric__icon metric__icon--green"><CircleDollarSign /></span><div><span>本月营收</span><strong>¥{{ data.monthlyRevenue.toLocaleString() }}</strong><small>较上月 +12.4%</small></div></article>
          <article class="metric"><span class="metric__icon metric__icon--violet"><TrendingUp /></span><div><span>转化率</span><strong>{{ data.conversionRate }}%</strong><small>目标 28%</small></div></article>
        </div>

        <section class="content-section">
          <div class="section-heading"><div><h2>最近动态</h2><p>系统内最新的业务活动</p></div></div>
          <div class="activity-list">
            <article v-for="activity in data.recentActivities" :key="activity.id" class="activity-row">
              <span class="activity-row__dot" :data-type="activity.type" />
              <div><strong>{{ activity.description }}</strong><span>{{ activity.occurredAt }}</span></div>
            </article>
          </div>
        </section>
      </template>
    </StatePanel>
  </section>
</template>
