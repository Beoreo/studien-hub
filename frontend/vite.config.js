import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Im Entwicklungsmodus leitet Vite alle /api-Aufrufe an das FastAPI-Backend weiter
// (STUDIENHUB_API z. B. für ein zweites Backend mit einer Datenbank-Kopie bei Screenshots).
export default defineConfig({
  plugins: [react()],
  server: {
    port: Number(process.env.VITE_PORT || 5173),
    proxy: { '/api': process.env.STUDIENHUB_API || 'http://127.0.0.1:8000' },
  },
})
