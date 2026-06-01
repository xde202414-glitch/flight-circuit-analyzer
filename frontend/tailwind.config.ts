import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#e3f2fd',
          100: '#bbdefb',
          200: '#90caf9',
          300: '#64b5f6',
          400: '#42a5f5',
          500: '#2196f3',
          600: '#1e88e5',
          700: '#1976d2',
          800: '#1565c0',
          900: '#0d47a1',
        },
        track: {
          departure: '#FF5722',
          turn: '#FFC107',
          crosswind: '#4CAF50',
          downwind: '#2196F3',
          base: '#9C27B0',
          final: '#F44336',
        },
      },
      spacing: {
        '18': '4.5rem',
        '22': '5.5rem',
      },
    },
  },
  plugins: [],
  // Avoid conflict with MUI
  corePlugins: {
    preflight: false,
  },
};

export default config;