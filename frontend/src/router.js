import { createRouter, createWebHistory } from "vue-router";

const routes = [
  {
    path: "/",
    name: "PortExpenses",
    component: () => import("@/pages/PortExpenses.vue"),
  },
  {
    path: "/manifest/:manifest",
    name: "PortExpensesForManifest",
    component: () => import("@/pages/PortExpenses.vue"),
    props: true,
  },
];

export default createRouter({
  history: createWebHistory("/port-expenses"),
  routes,
});
