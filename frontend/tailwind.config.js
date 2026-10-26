/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        background: '#f5f2e8',
        surface: '#f8f6ef',
        'surface-muted': '#eee9da',
        navy: '#10224a',
        'navy-deep': '#0b1737',
        'navy-card': '#0c1a3b',
        border: '#c9c1ab',
        'border-subtle': '#ded8c9',
        'border-dark': '#233257',
        'accent-gold': '#f4c52f',
        'accent-gold-soft': '#f9df72',
        'text-primary': '#08090c',
        'text-secondary': '#41434a',
        'text-muted': '#636159', // darkened to pass WCAG AA on ivory background
        'text-navy-muted': '#8b9bb4',
        // Semantic Risk States (accessible fixed mapping)
        risk: {
          normal: '#42b883',
          watch: '#64cbe3',
          high: '#e8bd45',
          critical: '#f17d75',
        }
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        heading: ['Space Grotesk', 'Inter', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      boxShadow: {
        'card-subtle': '0 1px 3px 0 rgba(0, 0, 0, 0.05), 0 1px 2px 0 rgba(0, 0, 0, 0.03)',
        'card-navy': '0 4px 20px -2px rgba(11, 23, 55, 0.35)',
        'gold-glow': '0 0 15px -3px rgba(244, 197, 47, 0.4)',
      },
    },
  },
  plugins: [],
}
