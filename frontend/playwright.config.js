import { defineConfig } from '@playwright/test';
import { fileURLToPath } from 'node:url';
const python = fileURLToPath(new URL('../.venv/bin/python', import.meta.url));
export default defineConfig({
  testDir: './tests/browser', timeout: 90000, workers: 1,
  use: {baseURL: 'http://127.0.0.1:5174', headless: true,
    launchOptions: {executablePath: process.env.CHROME_PATH || '/usr/bin/google-chrome', args: ['--enable-unsafe-swiftshader']},
    screenshot: 'only-on-failure'},
  webServer: [
    {command: 'npm run dev -- --port 5174 --strictPort', env: {SKYTRACKER_API_TARGET: 'http://127.0.0.1:8001'}, url: 'http://127.0.0.1:5174', reuseExistingServer: false},
    {command: `"${python}" -m uvicorn backend.app.main:app --app-dir .. --host 127.0.0.1 --port 8001`, url: 'http://127.0.0.1:8001/api/health', reuseExistingServer: false},
  ],
});
