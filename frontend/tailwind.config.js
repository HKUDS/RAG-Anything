/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontSize: {
        '2xs':  ['0.75rem',   { lineHeight: '1rem' }],        // 12px  (was 11px)
        'xs':   ['0.8125rem', { lineHeight: '1.25rem' }],     // 13px  (was 12px)
        'sm':   ['0.9375rem', { lineHeight: '1.5rem' }],      // 15px  (was 14px)
        'base': ['1rem',      { lineHeight: '1.625rem' }],    // 16px  (was 15px) — WCAG minimum
        'lg':   ['1.125rem',  { lineHeight: '1.75rem' }],     // 18px  (was 17px)
        'xl':   ['1.375rem',  { lineHeight: '1.875rem' }],    // 22px  (was 20px)
        '2xl':  ['1.625rem',  { lineHeight: '2.125rem' }],    // 26px  (was 24px)
        '3xl':  ['2rem',      { lineHeight: '2.5rem' }],      // 32px  (was 30px)
      },
      colors: {
        // === Cloud-Blue Neutral Scale (blue-tinted, replaces warm) ===
        cloud: {
          50:  '#f8fafd',  // surface hover
          100: '#f4f8fc',  // body bg (cloud-bg)
          200: '#edf3f9',  // well bg (was #f0f5fa — slightly defined)
          300: '#d6e5f2',  // border (was #e3eef7 — strengthened)
          400: '#bcd3e8',  // border strong (was #c7ddf0)
          500: '#8da3bb',  // muted icons (was #9aaec5 — darker)
        },
        // === Ink Text Scale (blue-gray, replaces warm text) ===
        ink: {
          muted:  '#557a95',  // secondary/label/placeholder (was #6b8aaa — 3.3→4.7:1 AA pass)
          body:   '#2d4d66',  // body text (was #3a5a78 — deepened for readability)
          primary:'#264860',  // headings (was #30567a — stronger presence)
          deep:   '#1a3448',  // darkest text (was #1f3d56)
        },
        // === Warm Neutral (legacy, kept for transition) ===
        warm: {
          50:  '#fefdfb',
          100: '#faf8f2',
          200: '#f3efe6',
          300: '#e8e2d6',
          400: '#b8b0a3',
          500: '#8a8276',
          600: '#6b6359',
          700: '#4a433b',
          800: '#2d2823',
          900: '#1a1613',
        },
        coral: {
          50:  '#fef7f4',
          100: '#fde9e0',
          200: '#fbd3c1',
          300: '#f7b398',
          400: '#f08f6d',
          500: '#e8734a',
          600: '#cd5a34',
          700: '#a8472a',
          800: '#863a24',
          900: '#662c1c',
        },
        sage: {
          50:  '#f5f8f3',
          100: '#e7efe2',
          200: '#d0e0c6',
          300: '#adc9a0',
          400: '#89b07a',
          500: '#6b9e7a',
          600: '#548063',
          700: '#43664f',
          800: '#385340',
          900: '#2f4436',
        },
        sky: {
          50:  '#f4f8fc',
          100: '#e3eef7',
          200: '#c7ddf0',
          300: '#9dc6e5',
          400: '#6da9d7',
          500: '#5b9bd5',
          600: '#3f7db8',
          700: '#366596',
          800: '#30567a',
          900: '#2b4966',
        },
        amber: {
          50:  '#fdfaf3',
          100: '#faf2e0',
          200: '#f4e3bf',
          300: '#eccf93',
          400: '#e0b86a',
          500: '#d4a853',
          600: '#b88c3d',
          700: '#966f32',
          800: '#7a5b2d',
          900: '#644c29',
        },
        rose: {
          50:  '#fdf5f6',
          100: '#fae9ec',
          200: '#f5d3d9',
          300: '#ecb0bb',
          400: '#de8597',
          500: '#c9707e',
          600: '#ad5261',
          700: '#91414f',
          800: '#783844',
          900: '#64323c',
        },
      },
      fontFamily: {
        display: ['"IBM Plex Sans"', '"PingFang SC"', '"Microsoft YaHei"', 'system-ui', 'sans-serif'],
        body: ['"IBM Plex Sans"', '"PingFang SC"', '"Microsoft YaHei"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', '"SF Mono"', '"Cascadia Code"', 'monospace'],
      },
      spacing: {
        '4.5': '1.125rem',
        '18':  '4.5rem',
        '88':  '22rem',
      },
      boxShadow: {
        // Cloud shadows — blue-tinted (ink-primary #264860) not pure black
        'cloud-sm': '0 1px 3px rgba(38,72,96,0.06), 0 1px 2px rgba(38,72,96,0.04)',
        'cloud':    '0 4px 16px rgba(38,72,96,0.08), 0 2px 4px rgba(38,72,96,0.04)',
        'cloud-md': '0 8px 30px rgba(38,72,96,0.10), 0 3px 8px rgba(38,72,96,0.05)',
        'cloud-lg': '0 16px 48px rgba(38,72,96,0.12), 0 4px 12px rgba(38,72,96,0.05)',
        // Legacy aliases (transitional)
        'warm-sm': '0 1px 3px rgba(38,72,96,0.06), 0 1px 2px rgba(38,72,96,0.04)',
        'warm':    '0 4px 16px rgba(38,72,96,0.08), 0 2px 4px rgba(38,72,96,0.04)',
        'warm-md': '0 8px 30px rgba(38,72,96,0.10), 0 3px 8px rgba(38,72,96,0.05)',
        'warm-lg': '0 16px 48px rgba(38,72,96,0.12), 0 4px 12px rgba(38,72,96,0.05)',
      },
      borderRadius: {
        '2xl': '0.875rem',
        '3xl': '1.25rem',
        '4xl': '1.75rem',
      },
      animation: {
        'fade-in':       'fadeIn 0.4s ease-out',
        'slide-up':      'slideUp 0.45s cubic-bezier(0.16, 1, 0.3, 1)',
        'slide-in-right':'slideInRight 0.35s cubic-bezier(0.16, 1, 0.3, 1)',
        'scale-in':      'scaleIn 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
        'float':         'float 3s ease-in-out infinite',
        'shimmer':       'shimmer 2s ease-in-out infinite',
        'pulse-soft':    'pulseSoft 2s ease-in-out infinite',
      },
      keyframes: {
        fadeIn:        { '0%': { opacity: '0' }, '100%': { opacity: '1' } },
        slideUp:       { '0%': { opacity: '0', transform: 'translateY(16px)' }, '100%': { opacity: '1', transform: 'translateY(0)' } },
        slideInRight:  { '0%': { opacity: '0', transform: 'translateX(24px)' }, '100%': { opacity: '1', transform: 'translateX(0)' } },
        scaleIn:       { '0%': { opacity: '0', transform: 'scale(0.93)' }, '100%': { opacity: '1', transform: 'scale(1)' } },
        float:         { '0%, 100%': { transform: 'translateY(0px)' }, '50%': { transform: 'translateY(-8px)' } },
        shimmer:       { '0%': { backgroundPosition: '-200% 0' }, '100%': { backgroundPosition: '200% 0' } },
        pulseSoft:     { '0%, 100%': { opacity: '1' }, '50%': { opacity: '0.5' } },
      },
      transitionDuration: {
        '400': '400ms',
      },
    },
  },
  plugins: [],
}
