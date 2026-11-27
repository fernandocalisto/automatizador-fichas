import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("pdfjs-dist")) return "vendor-pdfjs";
          if (id.includes("@monaco-editor") || id.includes("monaco-editor")) {
            return "vendor-monaco";
          }
          if (id.includes("@dnd-kit")) return "vendor-dndkit";
          if (id.includes("lucide-react")) return "vendor-icons";
          if (id.includes("react-dom") || id.includes("/react/") || id.includes("\\react\\")) {
            return "vendor-react";
          }
          return undefined;
        },
      },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: true,
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
