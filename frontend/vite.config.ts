import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api':      'http://localhost:8000',
      '/scan':     'http://localhost:8000',
      '/prospect': 'http://localhost:8000',
      '/stream':   'http://localhost:8000',
      '/config':   'http://localhost:8000',
      '/run':      'http://localhost:8000',
      '/upload':   'http://localhost:8000',
      '/download': 'http://localhost:8000',
      '/export':   'http://localhost:8000',
      '/cancel':   'http://localhost:8000',
      '/status':   'http://localhost:8000',
      '/admin':    'http://localhost:8000',
      '/oracle':   'http://localhost:8000',
    }
  }
})
