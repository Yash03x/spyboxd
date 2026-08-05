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
        // Terminal design tokens. CSS-variable-backed so one `data-theme` flip
        // on <html> switches the whole product. The cinema/noir palettes the
        // pre-redesign shell used left with it.
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
      },
      fontFamily: {
        // IBM Plex Sans and Mono, self-hosted by next/font -- exactly one copy
        // of each and no external stylesheet request.
        sans: ['var(--font-sans)', 'system-ui', '-apple-system', 'sans-serif'],
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
        t14: ['14px', { lineHeight: '19px' }],
      },
      letterSpacing: {
        // .12em on panel titles, .08em on the section crumb, .06em on tabs and
        // table headers, -.02em on the h1.
        title: '.12em',
        crumb: '.08em',
        tab: '.06em',
        head: '-.02em',
      },
    },
  },
  plugins: [],
}
