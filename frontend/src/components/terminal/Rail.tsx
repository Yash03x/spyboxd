'use client';

import Link from 'next/link';
import React from 'react';
import { useUser } from '@clerk/nextjs';
import {
  Clapperboard,
  Database,
  GitBranch,
  LayoutGrid,
  Popcorn,
  Radio,
  UsersRound,
} from 'lucide-react';
import { SECTIONS, type SectionDef, type SectionId } from './sections';

const ICONS = {
  'layout-grid': LayoutGrid,
  radio: Radio,
  'users-round': UsersRound,
  popcorn: Popcorn,
  clapperboard: Clapperboard,
  database: Database,
} as const;

function initialsFor(name: string | null | undefined): string {
  if (!name) return '··';
  const trimmed = name.replace(/^@/, '');
  return trimmed.slice(0, 2).toUpperCase();
}

function RailItem({ section, active }: { section: SectionDef; active: boolean }) {
  const Icon = ICONS[section.icon];
  return (
    <Link
      href={section.legacyPath ?? `/${section.id}`}
      title={`${section.ordinal} · ${section.name}`}
      aria-label={`${section.ordinal} ${section.name}`}
      aria-current={active ? 'page' : undefined}
      className="relative grid h-[34px] w-[38px] place-items-center rounded-[4px] no-underline hover:no-underline"
      style={{
        background: active ? 'color-mix(in srgb, var(--accent) 16%, transparent)' : 'transparent',
        color: active ? 'var(--accent)' : 'var(--muted)',
      }}
    >
      <span
        className="absolute bottom-[7px] left-[-7px] top-[7px] w-[2px]"
        style={{ background: active ? 'var(--accent)' : 'transparent' }}
      />
      <Icon size={17} aria-hidden />
    </Link>
  );
}

/**
 * The 52px icon rail. On viewports under 900px it becomes a bottom tab bar
 * with 44px hit targets -- see the `md:` breakpoints below and the matching
 * padding on the shell.
 */
export default function Rail({ active }: { active: SectionId }) {
  const { user } = useUser();
  const initials = initialsFor(
    (user?.username as string | undefined) ?? user?.firstName ?? user?.primaryEmailAddress?.emailAddress,
  );

  return (
    <nav
      aria-label="Sections"
      className="fixed inset-x-0 bottom-0 z-[60] flex h-[52px] flex-row items-center justify-around border-t border-term-rule bg-term-bg2 px-2 md:sticky md:top-0 md:h-screen md:w-[52px] md:shrink-0 md:flex-col md:justify-start md:gap-[2px] md:self-start md:border-r md:border-t-0 md:px-0 md:py-[10px]"
    >
      <span className="hidden h-8 w-8 place-items-center rounded-[4px] bg-term-accent text-[15px] font-extrabold text-term-onaccent md:mb-3 md:grid">
        S
      </span>

      {SECTIONS.map((section) => (
        <RailItem key={section.id} section={section} active={section.id === active} />
      ))}

      <span className="hidden flex-1 md:block" />

      <Link
        href="/architecture"
        title="Architecture map"
        className="hidden h-[34px] w-[38px] place-items-center rounded-[4px] text-term-muted no-underline hover:text-term-accent hover:no-underline md:grid"
      >
        <GitBranch size={16} aria-hidden />
      </Link>
      <span className="my-[6px] hidden h-px w-7 bg-term-rule md:block" />
      <span className="hidden h-[30px] w-[30px] place-items-center rounded-full border border-term-rule3 bg-term-panelhd text-t10 font-bold text-term-ink3 md:grid">
        {initials}
      </span>
    </nav>
  );
}
