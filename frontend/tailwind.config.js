/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: { 900: '#0a0a0f', 800: '#12121a', 700: '#1a1a25', 600: '#252533' },
        neon: { 400: '#60a5fa', 500: '#3b82f6', 600: '#2563eb' },
      },
      fontFamily: {
        display: ['"JetBrains Mono"', 'monospace'],
        body: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'],
      }
    },
  },
  plugins: [],
}
