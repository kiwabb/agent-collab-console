import { createRouter, createWebHistory } from "vue-router";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/dashboard" },
    {
      path: "/dashboard",
      name: "dashboard",
      component: () => import("./pages/DashboardPage.vue"),
    },
    {
      path: "/users",
      name: "users",
      component: () => import("./pages/UsersPage.vue"),
    },
    {
      path: "/orders",
      name: "orders",
      component: () => import("./pages/OrdersPage.vue"),
    },
    { path: "/:pathMatch(.*)*", redirect: "/dashboard" },
  ],
});

export default router;
