'use client';

import React from 'react';
import { Moon, Sun } from 'lucide-react';

export type Theme = 'dark' | 'light';

export const THEME_STORAGE_KEY = 'spyboxd-theme';

/**
 * Runs before first paint so the page never renders in the wrong theme and
 * then snaps. Kept as a string because it has to be inlined into <head>.
 *
 * `prefers-color-scheme` is consulted on the first visit only -- once somebody
 * has chosen, their choice outranks the OS.
 */
export const THEME_INIT_SCRIPT = `(function(){try{var t=localStorage.getItem('${THEME_STORAGE_KEY}');if(t!=='light'&&t!=='dark'){t=window.matchMedia&&window.matchMedia('(prefers-color-scheme: light)').matches?'light':'dark';}document.documentElement.dataset.theme=t;}catch(e){document.documentElement.dataset.theme='dark';}})();`;

function readTheme(): Theme {
  if (typeof document === 'undefined') return 'dark';
  return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
}

export function useTheme(): [Theme, () => void] {
  // Starts at 'dark' on both server and client so hydration agrees; the effect
  // below immediately corrects it from the attribute the init script set.
  const [theme, setTheme] = React.useState<Theme>('dark');

  React.useEffect(() => {
    setTheme(readTheme());
  }, []);

  const toggle = React.useCallback(() => {
    setTheme((current) => {
      const next: Theme = current === 'light' ? 'dark' : 'light';
      document.documentElement.dataset.theme = next;
      try {
        localStorage.setItem(THEME_STORAGE_KEY, next);
      } catch {
        // Private mode. The toggle still works for this session.
      }
      return next;
    });
  }, []);

  return [theme, toggle];
}

export function ThemeToggle() {
  const [theme, toggle] = useTheme();
  const Icon = theme === 'light' ? Moon : Sun;

  return (
    <button
      type="button"
      onClick={toggle}
      title="Toggle light mode"
      className="inline-flex items-center gap-[5px] rounded-[3px] border border-term-rule px-[7px] py-[3px] font-term text-t105 text-term-ink3 hover:border-term-accent hover:text-term-accent"
    >
      <Icon size={11} aria-hidden />
      {theme === 'light' ? 'DARK' : 'LIGHT'}
    </button>
  );
}
