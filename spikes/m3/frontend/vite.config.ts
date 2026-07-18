import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const baseline = mode === "baseline";
  return {
    plugins: [react()],
    define: {
      "process.env.NODE_ENV": JSON.stringify(mode === "development" ? "development" : "production"),
    },
    build: {
      outDir: baseline ? "dist-baseline" : "dist",
      manifest: true,
      sourcemap: true,
      rollupOptions: {
        input: baseline ? "baseline.html" : "index.html",
        output: {
          manualChunks(id) {
            if (id.includes("node_modules/echarts") || id.includes("node_modules/zrender")) return "echarts";
            if (id.includes("node_modules/react-grid-layout") || id.includes("node_modules/react-resizable")) return "layout";
            return undefined;
          },
        },
      },
    },
  };
});
