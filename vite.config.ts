import { defineConfig } from 'vite';
import { resolve } from 'path';

export default defineConfig({
  base: '/static/',
  root: 'src',
  publicDir: '../taui/static/public',
  build: {
    outDir: '../taui/static',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'src/index.html'),
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/ws': {
        target: 'http://localhost:8000',
        ws: true,
        changeOrigin: true,
      },
      '/healthz': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/static': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
});
