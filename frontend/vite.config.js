import path from "path";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import frappeui from "frappe-ui/vite";

export default defineConfig({
  plugins: [
    frappeui({
      frontendRoute: "/port-expenses",
      buildConfig: {
        outDir: "../icd_tz/public/frontend",
        baseUrl: "/assets/icd_tz/frontend/",
        // www page names cannot carry a hyphen, frappe imports them as modules
        indexHtmlPath: "../icd_tz/www/port_expenses.html",
        // the built assets are committed, so keep the maps out of the repo
        sourcemap: false,
      },
    }),
    vue(),
  ],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  build: {
    target: "es2015",
  },
});
