import { IBM_Plex_Sans, JetBrains_Mono } from 'next/font/google';

// The terminal redesign is a two-typeface product: mono for every number,
// label, tab, chip and table header; sans for prose, film titles and blurbs.
// Both are loaded through next/font so the CSS variables exist before first
// paint -- a webfont that arrives late reflows a 106-panel grid visibly.
export const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700', '800'],
  variable: '--font-mono',
  display: 'swap',
});

export const ibmPlexSans = IBM_Plex_Sans({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  variable: '--font-sans',
  display: 'swap',
});
