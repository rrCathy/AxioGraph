import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      }
    }
  },
  build: {
    // Set after splitting; this is a reporting threshold, not a way to hide warnings.
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/cytoscape')) return 'vendor-cytoscape'
          if (id.includes('node_modules/katex')) return 'vendor-katex'
          if (id.includes('node_modules/@tiptap') || id.includes('node_modules/prosemirror')) return 'vendor-editor'
          if (id.includes('node_modules/tesseract.js')) return 'vendor-ocr'
          if (id.includes('node_modules/react') || id.includes('node_modules/react-dom') ||
              id.includes('node_modules/scheduler') || id.includes('node_modules/zustand')) return 'vendor-react'
        },
      },
    },
  },
})
