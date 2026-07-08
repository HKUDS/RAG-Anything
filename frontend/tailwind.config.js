/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontSize: {
        '2xs':  ['0.75rem',  { lineHeight: '1rem' }],
        'xs':   ['0.75rem',  { lineHeight: '1rem' }],
        'sm':   ['0.875rem', { lineHeight: '1.25rem' }],
        'base': ['1rem',     { lineHeight: '1.5rem' }],
        'lg':   ['1.25rem',  { lineHeight: '1.75rem' }],
        'xl':   ['1.5rem',   { lineHeight: '2rem' }],
        '2xl':  ['2rem',     { lineHeight: '2.5rem', letterSpacing: '-0.01em' }],
        '3xl':  ['3rem',     { lineHeight: '3.5rem', letterSpacing: '-0.01em' }],
        '4xl':  ['4rem',     { lineHeight: '4.5rem', letterSpacing: '-0.01em' }],
      },
      colors: {
        /*
         * ═══════════════════════════════════════════════════════════════
         * Neutral Modern 设计系统色板
         *
         * 保留原有 Tailwind 类名（cloud/ink/sky/sage/amber/rose/coral）
         * 仅替换色值为 Neutral Modern 等价色，确保所有 JSX 页面无需改动。
         *
         * 映射关系：
         *   cloud → 中性灰阶（#FAFAFA → #737373）
         *   ink   → 前景文字色（#6B6B6B → #111111）
         *   sky   → 钴蓝强调色（#2F6FEB accent）
         *   sage  → 成功绿（#17A34A）
         *   amber → 警告黄（#EAB308）
         *   rose  → 危险红（#DC2626）
         *   coral → 暖强调色（保留用于头像/装饰）
         * ═══════════════════════════════════════════════════════════════
         */

        // ── 中性灰 Surface（原 cloud）────────────────────────────────
        // Neutral Modern: bg=#FAFAFA, surface=#FFFFFF, border=#E5E5E5
        cloud: {
          50:  '#fafafa',  // 页面背景 (--bg)
          100: '#fafafa',  // body bg 别名
          200: '#f5f5f5',  // well bg / hover
          300: '#e5e5e5',  // 边框 (--border)
          400: '#d4d4d4',  // 边框强色
          500: '#a3a3a3',  // 静默图标
        },

        // ── 前景文字（原 ink）────────────────────────────────────────
        // Neutral Modern: fg=#111111, muted=#6B6B6B
        ink: {
          muted:   '#6b6b6b',  // 次要文字 / 标签 / 占位符 (--muted)
          body:    '#404040',  // 正文
          primary: '#262626',  // 标题
          deep:    '#111111',  // 最深文字 (--fg)
        },

        // ── 钴蓝强调色（原 sky）─────────────────────────────────────
        // Neutral Modern accent: #2F6FEB
        sky: {
          50:  '#eff6ff',
          100: '#dbeafe',
          200: '#bfdbfe',
          300: '#93c5fd',
          400: '#60a5fa',
          500: '#2f6feb',  // 主强调色 (--accent)
          600: '#2563eb',
          700: '#1d4ed8',
          800: '#1e40af',
          900: '#1e3a8a',
        },

        // ── 成功绿（原 sage）────────────────────────────────────────
        // Neutral Modern success: #17A34A
        sage: {
          50:  '#f0fdf4',
          100: '#dcfce7',
          200: '#bbf7d0',
          300: '#86efac',
          400: '#4ade80',
          500: '#22c55e',
          600: '#17a34a',  // (--success)
          700: '#15803d',
          800: '#166534',
          900: '#14532d',
        },

        // ── 警告黄（原 amber）────────────────────────────────────────
        // Neutral Modern warn: #EAB308
        amber: {
          50:  '#fefce8',
          100: '#fef9c3',
          200: '#fef08a',
          300: '#fde047',
          400: '#facc15',
          500: '#eab308',  // (--warn)
          600: '#ca8a04',
          700: '#a16207',
          800: '#854d0e',
          900: '#713f12',
        },

        // ── 危险红（原 rose）────────────────────────────────────────
        // Neutral Modern danger: #DC2626
        rose: {
          50:  '#fef2f2',
          100: '#fee2e2',
          200: '#fecaca',
          300: '#fca5a5',
          400: '#f87171',
          500: '#ef4444',
          600: '#dc2626',  // (--danger)
          700: '#b91c1c',
          800: '#991b1b',
          900: '#7f1d1d',
        },

        // ── 暖强调色（原 coral）─────────────────────────────────────
        // 保留用于头像、装饰性暖色调点缀（非 Neutral Modern 核心令牌）
        coral: {
          50:  '#f5f5f5',
          100: '#e5e5e5',
          200: '#d4d4d4',
          300: '#a3a3a3',
          400: '#737373',
          500: '#525252',
          600: '#404040',
          700: '#262626',
          800: '#171717',
          900: '#111111',
        },

        // ── 暖中性色（原 warm）─ 保留供过渡使用 ────────────────────
        warm: {
          50:  '#fafafa',
          100: '#f5f5f5',
          200: '#e5e5e5',
          300: '#d4d4d4',
          400: '#a3a3a3',
          500: '#737373',
          600: '#525252',
          700: '#404040',
          800: '#262626',
          900: '#171717',
        },
      },
      fontFamily: {
        // Neutral Modern: Inter 用于展示和正文
        display: ['"Inter"', '"PingFang SC"', '"Microsoft YaHei"', 'system-ui', 'sans-serif'],
        body:    ['"Inter"', '"PingFang SC"', '"Microsoft YaHei"', 'system-ui', 'sans-serif'],
        mono:    ['"JetBrains Mono"', '"SF Mono"', '"Cascadia Code"', 'monospace'],
      },
      spacing: {
        '4.5': '1.125rem',
        '18':  '4.5rem',
        '88':  '22rem',
      },
      boxShadow: {
        /*
         * ═══════════════════════════════════════════════════════════════
         * Neutral Modern 阴影系统
         *
         * 仅两层：flat (none) + raised。
         * raised: 0 2px 8px rgba(0,0,0,0.08)
         * 所有阴影使用纯黑透明度，不含蓝色调。
         * ═══════════════════════════════════════════════════════════════
         */
        'cloud-sm': 'none',
        'cloud':    '0 2px 8px rgba(0,0,0,0.08)',
        'cloud-md': '0 2px 8px rgba(0,0,0,0.08)',
        'cloud-lg': '0 2px 8px rgba(0,0,0,0.08)',
        // 旧别名
        'warm-sm': 'none',
        'warm':    '0 2px 8px rgba(0,0,0,0.08)',
        'warm-md': '0 2px 8px rgba(0,0,0,0.08)',
        'warm-lg': '0 2px 8px rgba(0,0,0,0.08)',
      },
      borderRadius: {
        // Neutral Modern: 按钮 8px, 卡片 12px
        '2xl': '0.75rem',   // 12px — 卡片
        '3xl': '1rem',      // 16px
        '4xl': '1.25rem',
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
