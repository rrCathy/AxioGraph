/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        surface: {
          base: '#0b0e14',
          raised: '#111622',
          overlay: '#181d2a',
          card: '#1c2233',
          hover: '#242a3d',
        },
        accent: {
          blue: '#5b8def',
          purple: '#a78bfa',
          green: '#4ade80',
          amber: '#fbbf24',
          red: '#f87171',
          cyan: '#22d3ee',
        },
        border: {
          subtle: '#1e2740',
          medium: '#2a334c',
          strong: '#3a4562',
        },
        text: {
          primary: '#e2e8f0',
          secondary: '#cbd5e1',
          muted: '#94a3b8',
          dim: '#64748b',
        },
      },
      fontFamily: {
        sans: ['Inter', 'SF Pro Display', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'Consolas', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.65rem', { lineHeight: '0.9rem' }],
      },
      borderRadius: {
        'xl': '0.75rem',
        '2xl': '1rem',
      },
    },
  },
  plugins: [],
}
