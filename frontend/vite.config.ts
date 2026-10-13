import { defineConfig, loadEnv } from 'vite'
import path from 'path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'


function figmaAssetResolver() {
  return {
    name: 'figma-asset-resolver',
    resolveId(id) {
      if (id.startsWith('figma:asset/')) {
        const filename = id.replace('figma:asset/', '')
        return path.resolve(__dirname, 'src/assets', filename)
      }
    },
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  return {
    plugins: [
      figmaAssetResolver(),
      // The React and Tailwind plugins are both required for Make, even if
      // Tailwind is not being actively used – do not remove them
      react(),
      tailwindcss(),
    ],
    resolve: {
      alias: {
        // Alias @ to the src directory
        '@': path.resolve(__dirname, './src'),
      },
    },

    // File types to support raw imports. Never add .css, .tsx, or .ts files to this.
    assetsInclude: ['**/*.svg', '**/*.csv'],

    server: {
      proxy: env.VITE_GEOSERVER_URL
        ? {
            // Proxies GeoServer requests through the dev server's own origin so
            // the browser never sees a cross-origin request — avoids needing CORS
            // configured on GeoServer at all (see .claude/GEOSERVER_SETUP.md).
            '/geoserver-proxy': {
              target: env.VITE_GEOSERVER_URL,
              changeOrigin: true,
              rewrite: (path) => path.replace(/^\/geoserver-proxy/, ''),
            },
          }
        : undefined,
    },
  }
})
