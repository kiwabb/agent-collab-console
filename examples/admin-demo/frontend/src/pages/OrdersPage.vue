<script setup lang="ts">
import { Download } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { api, type Order } from "../api";
import StatePanel from "../components/StatePanel.vue";

const orders = ref<Order[]>([]);
const loading = ref(true);
const error = ref("");

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try { orders.value = await api.getOrders(); }
  catch (cause) { console.error("Failed to load orders", cause); error.value = cause instanceof Error ? cause.message : "未知错误"; }
  finally { loading.value = false; }
}

function statusLabel(status: Order["status"]): string {
  return { paid: "已支付", pending: "待支付", refunded: "已退款" }[status];
}

onMounted(load);
</script>

<template>
  <section>
    <div class="page-heading"><div><span class="eyebrow">交易与履约</span><h1>订单管理</h1><p>跟踪近期订单金额和处理状态。</p></div><button class="secondary-button"><Download :size="17" />导出订单</button></div>
    <StatePanel :loading="loading" :error="error" @retry="load">
      <section class="content-section">
        <div class="section-heading"><div><h2>全部订单</h2><p>最近创建的 {{ orders.length }} 笔订单</p></div></div>
        <div class="table-scroll"><table><thead><tr><th>订单号</th><th>客户</th><th>商品</th><th>金额</th><th>状态</th><th>创建时间</th></tr></thead>
          <tbody><tr v-for="order in orders" :key="order.id"><td><strong class="order-id">{{ order.id }}</strong></td><td>{{ order.customerName }}</td><td>{{ order.product }}</td><td class="number">¥{{ order.amount.toLocaleString() }}</td><td><span class="status" :data-status="order.status">{{ statusLabel(order.status) }}</span></td><td>{{ order.createdAt }}</td></tr></tbody>
        </table></div>
      </section>
    </StatePanel>
  </section>
</template>
