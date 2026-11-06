/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    screens: {
      sm: '640px',
      lg: '1024px',
      xl: '1280px',
    },
    extend: {
      colors: {
        'surface-page': 'var(--surface-page)',
        'surface-raised': 'var(--surface-raised)',
        'surface-subtle': 'var(--surface-subtle)',
        'text-primary': 'var(--text-primary)',
        'text-secondary': 'var(--text-secondary)',
        'border-default': 'var(--border-default)',
        'action-primary': 'var(--action-primary)',
        'action-primary-hover': 'var(--action-primary-hover)',
        'feedback-success': 'var(--feedback-success)',
        'feedback-warning': 'var(--feedback-warning)',
        'feedback-error': 'var(--feedback-error)',
        'feedback-info': 'var(--feedback-info)',
      },
      fontFamily: {
        sans: [
          '-apple-system',
          'BlinkMacSystemFont',
          '"Segoe UI"',
          '"PingFang SC"',
          '"Microsoft YaHei"',
          'sans-serif',
        ],
        mono: [
          'ui-monospace',
          'SFMono-Regular',
          'Consolas',
          '"Liberation Mono"',
          'Menlo',
          'monospace',
        ],
      },
      maxWidth: {
        stage: '1200px',
        reading: '760px',
      },
      borderRadius: {
        control: '8px',
      },
    },
  },
  plugins: [],
};
