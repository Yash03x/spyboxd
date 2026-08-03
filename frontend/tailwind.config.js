/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/**/*.{js,jsx,ts,tsx,mdx}",
    "./src/app/**/*.{js,jsx,ts,tsx,mdx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Terminal redesign tokens. These are CSS-variable-backed so one
        // `data-theme` flip on <html> switches the whole product, and they sit
        // beside the cinema/noir scales rather than replacing them so the
        // not-yet-migrated views keep working.
        term: {
          bg: 'var(--bg)',
          bg2: 'var(--bg2)',
          panel: 'var(--panel)',
          panelhd: 'var(--panelhd)',
          track: 'var(--track)',
          heat0: 'var(--heat0)',
          rule: 'var(--rule)',
          rule2: 'var(--rule2)',
          rule3: 'var(--rule3)',
          ink: 'var(--ink)',
          ink2: 'var(--ink2)',
          ink3: 'var(--ink3)',
          muted: 'var(--muted)',
          muted2: 'var(--muted2)',
          dim: 'var(--dim)',
          dim2: 'var(--dim2)',
          dim3: 'var(--dim3)',
          barmuted: 'var(--barmuted)',
          accent: 'var(--accent)',
          accent2: 'var(--accent2)',
          onaccent: 'var(--onaccent)',
          ok: 'var(--ok)',
          bad: 'var(--bad)',
          blue: 'var(--blue)',
        },
        // Cinema-inspired primary palette
        cinema: {
          50: '#fef7ee',
          100: '#fde8d3',
          200: '#fbcd9a',
          300: '#f8a761',
          400: '#f57c00',
          500: '#e65100',
          600: '#c44100',
          700: '#992e00',
          800: '#7a1f00',
          900: '#5d1600',
        },
        // Film noir grays
        noir: {
          50: '#f8fafc',
          100: '#f1f5f9',
          200: '#e2e8f0',
          300: '#cbd5e1',
          400: '#94a3b8',
          500: '#64748b',
          600: '#475569',
          700: '#334155',
          800: '#1e293b',
          900: '#0f172a',
        },
        // Keep primary for compatibility
        primary: {
          50: '#fef7ee',
          100: '#fde8d3',
          200: '#fbcd9a',
          300: '#f8a761',
          400: '#f57c00',
          500: '#e65100',
          600: '#c44100',
          700: '#992e00',
          800: '#7a1f00',
          900: '#5d1600',
        },
      },
      fontFamily: {
        // IBM Plex Sans replaces Inter as the product's sans. Both families are
        // self-hosted by next/font, so there is exactly one copy of each and no
        // external stylesheet request.
        sans: ['var(--font-sans)', 'system-ui', '-apple-system', 'sans-serif'],
        display: ['var(--font-sans)', 'system-ui', 'sans-serif'],
        mono: ['var(--font-mono)', 'ui-monospace', 'Consolas', 'monospace'],
        // The redesign's two faces, wired to next/font's generated variables.
        term: ['var(--font-mono)', 'ui-monospace', 'monospace'],
        'term-sans': ['var(--font-sans)', 'system-ui', 'sans-serif'],
      },
      fontSize: {
        // A dense, deliberately un-rounded scale. Rounding these into
        // Tailwind's default steps collapses distinctions the design uses --
        // 9px table headers against 9.5px units against 10px caveats.
        t85: ['8.5px', { lineHeight: '12px' }],
        t9: ['9px', { lineHeight: '13px' }],
        t95: ['9.5px', { lineHeight: '13px' }],
        t10: ['10px', { lineHeight: '15px' }],
        t105: ['10.5px', { lineHeight: '16px' }],
        t11: ['11px', { lineHeight: '15px' }],
        t115: ['11.5px', { lineHeight: '16px' }],
        t12: ['12px', { lineHeight: '17px' }],
        t13: ['13px', { lineHeight: '18px' }],
        t19: ['19px', { lineHeight: '22px' }],
        t20: ['20px', { lineHeight: '24px' }],
        t21: ['21px', { lineHeight: '24px' }],
        t22: ['22px', { lineHeight: '26px' }],
        t30: ['30px', { lineHeight: '34px' }],
        '2xs': ['0.625rem', { lineHeight: '0.75rem' }],
        'xs': ['0.75rem', { lineHeight: '1rem' }],
        'sm': ['0.875rem', { lineHeight: '1.25rem' }],
        'base': ['1rem', { lineHeight: '1.5rem' }],
        'lg': ['1.125rem', { lineHeight: '1.75rem' }],
        'xl': ['1.25rem', { lineHeight: '1.75rem' }],
        '2xl': ['1.5rem', { lineHeight: '2rem' }],
        '3xl': ['1.875rem', { lineHeight: '2.25rem' }],
        '4xl': ['2.25rem', { lineHeight: '2.5rem' }],
        '5xl': ['3rem', { lineHeight: '1' }],
        '6xl': ['3.75rem', { lineHeight: '1' }],
        '7xl': ['4.5rem', { lineHeight: '1' }],
      },
      letterSpacing: {
        // .12em on panel titles, .08em on the section crumb, .06em on tabs and
        // table headers, -.02em on the h1.
        title: '.12em',
        crumb: '.08em',
        tab: '.06em',
        head: '-.02em',
      },
      boxShadow: {
        'glow': '0 0 20px rgba(229, 81, 0, 0.3)',
        'glow-lg': '0 0 40px rgba(229, 81, 0, 0.2)',
        'cinema': '0 10px 30px rgba(229, 81, 0, 0.15)',
        'glass': '0 8px 32px rgba(31, 38, 135, 0.37)',
        'soft': '0 2px 15px rgba(0, 0, 0, 0.08)',
        'lift': '0 4px 20px rgba(0, 0, 0, 0.1)',
      },
      backdropBlur: {
        'xs': '2px',
        'sm': '4px',
        'md': '8px',
        'lg': '12px',
        'xl': '16px',
        '2xl': '24px',
        '3xl': '40px',
      },
      animation: {
        'rise-in': 'riseIn 0.4s cubic-bezier(0.25, 0.46, 0.45, 0.94)',
        'fade-in': 'fadeIn 0.5s ease-in-out',
        'fade-up': 'fadeUp 0.5s ease-out',
        'slide-in': 'slideIn 0.3s ease-out',
        'scale-in': 'scaleIn 0.2s ease-out',
        'bounce-soft': 'bounceSoft 0.6s ease-out',
        'glow': 'glow 2s ease-in-out infinite alternate',
        'float': 'float 3s ease-in-out infinite',
        'shimmer': 'shimmer 2s linear infinite',
      },
      keyframes: {
        // Entrance for anything whose visibility matters. Every other keyframe
        // here starts at `opacity: 0`, which makes the animation own whether
        // the content can be seen -- and an animation clock that never advances
        // (a background tab freezes it at 0%) then leaves the page blank. This
        // one only moves, so a frozen clock costs a few pixels of offset
        // instead of the entire page.
        riseIn: {
          '0%': { transform: 'translateY(12px)' },
          '100%': { transform: 'translateY(0)' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        fadeUp: {
          '0%': { 
            opacity: '0', 
            transform: 'translateY(20px)' 
          },
          '100%': { 
            opacity: '1', 
            transform: 'translateY(0)' 
          },
        },
        slideIn: {
          '0%': { 
            opacity: '0', 
            transform: 'translateX(-20px)' 
          },
          '100%': { 
            opacity: '1', 
            transform: 'translateX(0)' 
          },
        },
        scaleIn: {
          '0%': { 
            opacity: '0', 
            transform: 'scale(0.9)' 
          },
          '100%': { 
            opacity: '1', 
            transform: 'scale(1)' 
          },
        },
        bounceSoft: {
          '0%, 20%, 50%, 80%, 100%': {
            transform: 'translateY(0)',
          },
          '40%': {
            transform: 'translateY(-10px)',
          },
          '60%': {
            transform: 'translateY(-5px)',
          },
        },
        glow: {
          '0%': {
            boxShadow: '0 0 20px rgba(229, 81, 0, 0.3)',
          },
          '100%': {
            boxShadow: '0 0 30px rgba(229, 81, 0, 0.5)',
          },
        },
        float: {
          '0%, 100%': {
            transform: 'translateY(0px)',
          },
          '50%': {
            transform: 'translateY(-10px)',
          },
        },
        shimmer: {
          '0%': {
            backgroundPosition: '-200% 0',
          },
          '100%': {
            backgroundPosition: '200% 0',
          },
        },
      },
      backgroundImage: {
        'gradient-radial': 'radial-gradient(var(--tw-gradient-stops))',
        'gradient-conic': 'conic-gradient(from 180deg at 50% 50%, var(--tw-gradient-stops))',
        'cinema-gradient': 'linear-gradient(135deg, #f57c00 0%, #e65100 50%, #c44100 100%)',
        'glass-gradient': 'linear-gradient(135deg, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0.05) 100%)',
      },
      blur: {
        'xs': '2px',
        'sm': '4px',
      },
    },
  },
  plugins: [],
}
