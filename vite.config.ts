import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import path from "node:path"

export default defineConfig({
  base: "/consumer/",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@olfy/client": path.resolve(
        import.meta.dirname,
        "../olfy/web/olfy-client.js",
      ),
    },
  },
  build: { outDir: "../olfy/web/consumer", emptyOutDir: true },
  server: {
    host: "127.0.0.1",
    proxy: { "/api": "http://127.0.0.1:8765", "/lab": "http://127.0.0.1:8765", "/setup": "http://127.0.0.1:8765", "/olfy-client.js": "http://127.0.0.1:8765" },
  },
})
