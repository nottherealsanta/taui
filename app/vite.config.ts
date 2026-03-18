import { defineConfig } from 'vitest/config'
import { svelte } from '@sveltejs/vite-plugin-svelte'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath } from 'url'

const resolve = (p: string) => fileURLToPath(new URL(p, import.meta.url))

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    tailwindcss(),
    svelte(),
  ],

  resolve: {
    alias: {
      $lib: resolve('./src/lib'),
      $components: resolve('./src/lib/components'),
      $stores: resolve('./src/lib/stores'),
      $services: resolve('./src/lib/services'),
      $types: resolve('./src/lib/types'),
    },
  },

  // Tauri dev config
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    host: '127.0.0.1',
    watch: {
      // Prevent watching the Rust source to avoid infinite reloads
      ignored: ['**/src-tauri/**'],
    },
  },

  // Build optimization: isolate Monaco into its own chunk
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          monaco: ['monaco-editor'],
        },
      },
    },
  },

  // Vitest configuration
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,svelte}'],
  },
})
