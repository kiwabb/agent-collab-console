<script setup lang="ts">
import { Bell, Boxes, LayoutDashboard, Menu, PackageCheck, Users, X } from "lucide-vue-next";
import { ref } from "vue";
import { RouterLink, RouterView } from "vue-router";

const isMenuOpen = ref(false);

const navigation = [
  { to: "/dashboard", label: "仪表盘", icon: LayoutDashboard },
  { to: "/users", label: "用户管理", icon: Users },
  { to: "/orders", label: "订单管理", icon: PackageCheck },
];
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar" :class="{ 'sidebar--open': isMenuOpen }">
      <div class="brand">
        <span class="brand__mark"><Boxes :size="20" /></span>
        <div>
          <strong>Northstar</strong>
          <span>运营管理平台</span>
        </div>
        <button class="icon-button sidebar__close" aria-label="关闭导航" @click="isMenuOpen = false">
          <X :size="20" />
        </button>
      </div>

      <nav class="navigation" aria-label="主导航">
        <RouterLink
          v-for="item in navigation"
          :key="item.to"
          :to="item.to"
          class="navigation__link"
          @click="isMenuOpen = false"
        >
          <component :is="item.icon" :size="19" />
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>

      <div class="sidebar__footer">
        <span class="avatar">陈</span>
        <div><strong>陈晓宁</strong><span>系统管理员</span></div>
      </div>
    </aside>

    <div v-if="isMenuOpen" class="scrim" @click="isMenuOpen = false" />

    <section class="main-column">
      <header class="topbar">
        <button class="icon-button mobile-menu" aria-label="打开导航" @click="isMenuOpen = true">
          <Menu :size="21" />
        </button>
        <span class="topbar__context">企业运营中心</span>
        <div class="topbar__actions">
          <button class="icon-button" aria-label="查看通知"><Bell :size="19" /></button>
          <span class="environment"><i />生产环境</span>
        </div>
      </header>

      <main id="main-content" class="page-container">
        <RouterView />
      </main>
    </section>
  </div>
</template>
