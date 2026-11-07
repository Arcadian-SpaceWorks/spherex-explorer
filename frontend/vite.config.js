import { defineConfig } from 'vite';
export default defineConfig({esbuild: {jsx: 'automatic'}, server: {proxy: {'/api': process.env.SKYTRACKER_API_TARGET || 'http://127.0.0.1:8000'}}});
