'use client';

import React, { useEffect, useId, useRef, useState } from 'react';
import { Check, ChevronDown, Users } from 'lucide-react';

import type { ProfileInfo } from '../../services/api';
import { ProfileAvatar } from './InsightUI';

interface ProfileMultiSelectProps {
  profiles: ProfileInfo[];
  selectedUsernames: string[];
  minSelection: number;
  maxSelection?: number;
  label: string;
  onChange: (next: string[]) => void;
  className?: string;
}

export default function ProfileMultiSelect({
  profiles,
  selectedUsernames,
  minSelection,
  maxSelection,
  label,
  onChange,
  className = '',
}: ProfileMultiSelectProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const labelId = useId();
  const panelId = useId();
  const selectedProfiles = profiles.filter((profile) => selectedUsernames.includes(profile.username));

  useEffect(() => {
    const handlePointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && open) {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [open]);

  const toggleProfile = (username: string) => {
    if (selectedUsernames.includes(username)) {
      onChange(selectedUsernames.filter((value) => value !== username));
      return;
    }
    if (maxSelection && selectedUsernames.length >= maxSelection) return;
    onChange([...selectedUsernames, username]);
  };

  return (
    <div ref={rootRef} className={`relative z-40 ${className}`}>
      <span id={labelId} className="sr-only">{label}</span>
      <button
        ref={triggerRef}
        type="button"
        aria-labelledby={labelId}
        aria-haspopup="true"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
        className="flex min-h-12 w-full items-center justify-between gap-3 rounded-xl border border-white/10 bg-black/20 px-3 text-left transition-colors hover:border-cinema-400/35 focus:outline-none focus-visible:ring-2 focus-visible:ring-cinema-400/70"
      >
        <span className="flex min-w-0 flex-1 items-center gap-1.5 overflow-hidden">
          {selectedProfiles.slice(0, 4).map((profile) => (
            <ProfileAvatar key={profile.username} profile={profile} size="sm" />
          ))}
          <span className="ml-1 truncate text-sm font-semibold text-white/85">
            {selectedProfiles.length === 0
              ? `Choose at least ${minSelection}`
              : `${selectedProfiles.length} selected`}
          </span>
        </span>
        <ChevronDown className={`h-4 w-4 shrink-0 text-white/45 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div
          id={panelId}
          role="group"
          aria-labelledby={labelId}
          className="absolute right-0 top-[calc(100%+0.5rem)] z-[100] flex max-h-[min(20rem,calc(100dvh-15rem))] w-[min(22rem,calc(100vw-2rem))] flex-col overflow-clip rounded-xl border border-white/15 bg-[#091525] shadow-2xl shadow-black/60 sm:max-h-80"
        >
          <div className="flex shrink-0 items-center justify-between border-b border-white/10 px-3 py-2">
            <span className="flex items-center gap-2 text-xs font-semibold text-white/65">
              <Users className="h-4 w-4 text-cinema-400" /> {label}
            </span>
            <button
              type="button"
              onClick={() => onChange(maxSelection ? profiles.slice(0, maxSelection).map((profile) => profile.username) : profiles.map((profile) => profile.username))}
              className="text-xs font-semibold text-cinema-300 hover:text-cinema-200"
            >
              Select all
            </button>
          </div>
          <div className="min-h-0 flex-1 overscroll-contain overflow-y-auto p-2 [scrollbar-gutter:stable]">
            {profiles.map((profile) => {
              const checked = selectedUsernames.includes(profile.username);
              const disabled = !checked && Boolean(maxSelection && selectedUsernames.length >= maxSelection);
              return (
                <label
                  key={profile.username}
                  className={`grid grid-cols-[1rem_1.75rem_minmax(0,1fr)] items-center gap-x-2 rounded-lg px-2.5 py-2 text-sm transition-colors ${disabled ? 'cursor-not-allowed opacity-40' : 'cursor-pointer hover:bg-white/[0.06]'}`}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={disabled}
                    onChange={() => toggleProfile(profile.username)}
                    className="peer sr-only"
                  />
                  <span className={`grid h-4 w-4 place-items-center rounded border peer-focus-visible:ring-2 peer-focus-visible:ring-cinema-300 peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-[#091525] ${checked ? 'border-cinema-400 bg-cinema-500 text-white' : 'border-white/25 bg-white/5'}`}>
                    {checked && <Check className="h-3 w-3" />}
                  </span>
                  <ProfileAvatar profile={profile} size="sm" />
                  <span className="min-w-0 leading-tight">
                    <span className="block truncate font-medium text-white/80" title={profile.username}>{profile.username}</span>
                    <span className="mt-0.5 block text-[11px] text-white/35">{profile.total_films.toLocaleString()} films</span>
                  </span>
                </label>
              );
            })}
          </div>
          <p className="shrink-0 border-t border-white/10 px-3 py-2 text-[11px] text-white/40">
            Select {minSelection}{maxSelection ? `–${maxSelection}` : '+'} profiles.
          </p>
        </div>
      )}
    </div>
  );
}
