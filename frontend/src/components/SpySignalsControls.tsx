'use client';

import React, { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown, Radar, Users } from 'lucide-react';

import type { ProfileInfo } from '../services/api';

export type SignalGapDays = 0 | 1 | 3;

interface SpySignalsControlsProps {
  profiles: ProfileInfo[];
  selectedProfiles: string[];
  gapDays: SignalGapDays;
  isScanning: boolean;
  onSelectionChange: (profiles: string[]) => void;
  onGapChange: (gapDays: SignalGapDays) => void;
  onScan: () => void;
}

const GAP_OPTIONS: Array<{ value: SignalGapDays; label: string }> = [
  { value: 0, label: 'Same day' },
  { value: 1, label: '1 day' },
  { value: 3, label: '3 days' },
];

function Initials({ username }: { username: string }) {
  return (
    <span
      aria-hidden="true"
      className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-cinema-400/30 bg-cinema-500/15 text-[10px] font-bold uppercase text-cinema-200"
    >
      {username.slice(0, 2)}
    </span>
  );
}

const SpySignalsControls: React.FC<SpySignalsControlsProps> = ({
  profiles,
  selectedProfiles,
  gapDays,
  isScanning,
  onSelectionChange,
  onGapChange,
  onScan,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const controlsRef = useRef<HTMLElement>(null);
  const allUsernames = profiles.map((profile) => profile.username);
  const allSelected = allUsernames.length > 0 && selectedProfiles.length === allUsernames.length;

  useEffect(() => {
    const closeOnOutsideClick = (event: MouseEvent) => {
      if (!controlsRef.current?.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setIsOpen(false);
    };

    document.addEventListener('mousedown', closeOnOutsideClick);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('mousedown', closeOnOutsideClick);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, []);

  const toggleProfile = (username: string) => {
    if (selectedProfiles.includes(username)) {
      onSelectionChange(selectedProfiles.filter((profile) => profile !== username));
      return;
    }

    onSelectionChange([...selectedProfiles, username]);
  };

  const previewProfiles = selectedProfiles.slice(0, 3);
  const overflowCount = Math.max(0, selectedProfiles.length - previewProfiles.length);

  return (
    <section ref={controlsRef} className="card-cinema p-4 sm:p-5" aria-label="Spy signal filters">
      <div className="grid gap-4 xl:grid-cols-[auto_minmax(20rem,1fr)_auto_auto] xl:items-end">
        <button
          type="button"
          aria-pressed={allSelected}
          onClick={() => {
            onSelectionChange(allUsernames);
            setIsOpen(false);
          }}
          className={`flex min-h-12 items-center justify-center gap-2 rounded-xl border px-4 text-sm font-semibold transition-all focus:outline-none focus:ring-2 focus:ring-cinema-400/60 xl:col-start-1 xl:row-start-1 ${
            allSelected
              ? 'border-cinema-400/40 bg-cinema-500/20 text-cinema-200 shadow-cinema'
              : 'border-white/15 bg-white/5 text-white/75 hover:border-white/25 hover:bg-white/10 hover:text-white'
          }`}
        >
          <Users className="h-5 w-5" />
          All Profiles
          {allSelected && <Check className="h-4 w-4" aria-hidden="true" />}
        </button>

        <div className="min-w-0 xl:col-start-2 xl:row-start-1">
          <label id="profile-selector-label" className="mb-2 block text-xs font-medium text-white/60">
            Profiles ({selectedProfiles.length} selected)
          </label>
          <button
            type="button"
            aria-labelledby="profile-selector-label"
            aria-haspopup="true"
            aria-expanded={isOpen}
            aria-controls="profile-selector-options"
            onClick={() => setIsOpen((open) => !open)}
            className="flex min-h-12 w-full items-center justify-between gap-3 rounded-xl border border-white/15 bg-black/10 px-3 text-left transition-colors hover:border-white/25 focus:outline-none focus:ring-2 focus:ring-cinema-400/60"
          >
            <span className="flex min-w-0 flex-1 items-center gap-2 overflow-hidden">
              {previewProfiles.map((username) => (
                <span
                  key={username}
                  className="flex min-w-0 items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 py-1 pl-1 pr-2 text-xs text-white/85"
                >
                  <Initials username={username} />
                  <span className="max-w-24 truncate">{username}</span>
                </span>
              ))}
              {overflowCount > 0 && (
                <span className="shrink-0 text-xs font-medium text-white/60">+{overflowCount}</span>
              )}
              {selectedProfiles.length === 0 && (
                <span className="text-sm text-white/45">Choose at least two profiles</span>
              )}
            </span>
            <ChevronDown
              className={`h-4 w-4 shrink-0 text-white/50 transition-transform ${isOpen ? 'rotate-180' : ''}`}
            />
          </button>
        </div>

        {isOpen && (
          <div
            id="profile-selector-options"
            role="group"
            aria-labelledby="profile-selector-label"
            className="grid max-h-80 grid-cols-1 gap-1 overflow-y-auto rounded-xl border border-white/15 bg-noir-900/90 p-2 shadow-inner backdrop-blur-xl sm:max-h-none sm:grid-cols-2 sm:overflow-visible xl:col-span-4 xl:col-start-1 xl:row-start-2 2xl:grid-cols-3"
          >
            {profiles.map((profile) => {
              const checked = selectedProfiles.includes(profile.username);
              return (
                <label
                  key={profile.username}
                  className="flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors hover:bg-white/10"
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggleProfile(profile.username)}
                    className="h-4 w-4 rounded border-white/30 bg-white/5 accent-orange-600"
                  />
                  <Initials username={profile.username} />
                  <span className="min-w-0 flex-1 truncate font-medium text-white/85">
                    {profile.username}
                  </span>
                  <span className="shrink-0 text-xs text-white/40">
                    {profile.total_films.toLocaleString()} films
                  </span>
                </label>
              );
            })}
            <p className="px-3 pb-1 pt-2 text-xs text-white/40 sm:col-span-2 2xl:col-span-3">
              At least two profiles are required for a scan.
            </p>
          </div>
        )}

        <fieldset className="xl:col-start-3 xl:row-start-1">
          <legend className="mb-2 block text-xs font-medium text-white/60">Time Gap</legend>
          <div className="grid min-h-12 grid-cols-3 overflow-hidden rounded-xl border border-white/15 bg-black/10">
            {GAP_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                aria-pressed={gapDays === option.value}
                onClick={() => onGapChange(option.value)}
                className={`min-w-20 px-3 text-sm font-medium transition-colors focus:z-10 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-cinema-400/60 ${
                  gapDays === option.value
                    ? 'bg-gradient-to-r from-cinema-500 to-cinema-600 text-white shadow-glow'
                    : 'border-l border-white/10 text-white/65 first:border-l-0 hover:bg-white/10 hover:text-white'
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        </fieldset>

        <button
          type="button"
          onClick={() => {
            setIsOpen(false);
            onScan();
          }}
          disabled={selectedProfiles.length < 2 || isScanning}
          className="btn-primary flex min-h-12 items-center justify-center gap-2 px-5 py-2.5 focus:outline-none focus:ring-2 focus:ring-cinema-300/70 disabled:hover:scale-100 xl:col-start-4 xl:row-start-1"
        >
          <Radar className={`h-5 w-5 ${isScanning ? 'animate-pulse' : ''}`} />
          <span>{isScanning ? 'Scanning…' : 'Scan Signals'}</span>
        </button>
      </div>
    </section>
  );
};

export default SpySignalsControls;
