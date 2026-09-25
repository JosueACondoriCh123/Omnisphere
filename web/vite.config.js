import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig(({ mode }) => {
  if (mode === 'vercel') {
    const env = loadEnv(mode, process.cwd(), 'VITE_')
    for (const [name, protocols] of [
      ['VITE_PUBLIC_API_ORIGIN', ['https:']],
      ['VITE_PUBLIC_WS_ORIGIN', ['wss:']],
    ]) {
      const value = env[name]?.trim()
      if (!value) continue
      let url
      try { url = new URL(value) } catch { throw new Error(`${name} debe ser un origen público válido`) }
      if (!protocols.includes(url.protocol) || url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
        throw new Error(`${name} debe ser un origen público ${protocols[0]} sin ruta ni credenciales`)
      }
    }
    if (env.VITE_PUBLIC_WS_ORIGIN && !env.VITE_PUBLIC_API_ORIGIN) {
      throw new Error('VITE_PUBLIC_WS_ORIGIN requiere VITE_PUBLIC_API_ORIGIN')
    }
  }
  return {
  plugins: [
    react(),
    VitePWA({
      registerType: 'prompt',
      injectRegister: false,
      manifest: false,
      includeAssets: ['icon.svg'],
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,webmanifest}'],
        navigateFallback: 'index.html',
        navigateFallbackDenylist: [/^\/api\//, /^\/ws\//],
        skipWaiting: true,
        clientsClaim: true,
        runtimeCaching: [
          {
            urlPattern: ({ url }) => url.pathname.startsWith('/api/'),
            handler: 'NetworkOnly',
          },
        ],
      },
      devOptions: { enabled: false },
    }),
  ],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8080',
      '/ws': { target: 'ws://127.0.0.1:8080', ws: true },
    },
  },
  preview: {
    proxy: {
      '/api': 'http://127.0.0.1:8080',
      '/ws': { target: 'ws://127.0.0.1:8080', ws: true },
    },
  },
  test: {
    environment: 'node',
    reporters: ['verbose'],
    exclude: ['e2e/**', 'vercel-e2e/**', 'server/**', 'node_modules/**', 'dist/**'],
  },
  }
})
