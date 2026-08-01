'use client';

import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Check, ChevronDown, Search } from 'lucide-react';

import type { ProfileInfo } from '../services/api';
import { ProfileAvatar } from './insights/InsightUI';

interface ProfilePickerProps {
  profiles: ProfileInfo[];
  /** Selected username, or '' when nothing is selected yet. */
  value: string;
  onChange: (username: string) => void;
  /** Accessible name for the combobox; rendered visibly when showLabel is set. */
  label: string;
  showLabel?: boolean;
  /** Secondary line under the field, e.g. a film count for the selected profile. */
  caption?: React.ReactNode;
  /** Usernames that stay visible but cannot be chosen (e.g. the other half of a pair). */
  disabledUsernames?: string[];
  placeholder?: string;
  className?: string;
}

function profileLabel(profile: ProfileInfo): string {
  return profile.display_name?.trim() || profile.username;
}

function matchesQuery(profile: ProfileInfo, query: string): boolean {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return true;
  return profile.username.toLocaleLowerCase().includes(needle)
    || (profile.display_name ?? '').toLocaleLowerCase().includes(needle);
}

/**
 * Walks the option list in `direction`, wrapping around and skipping blocked
 * entries. Returns -1 when nothing selectable is left.
 */
function nextSelectableIndex(
  options: ProfileInfo[],
  blocked: Set<string>,
  from: number,
  direction: 1 | -1,
): number {
  const count = options.length;
  if (count === 0) return -1;
  let index = from;
  if (index < 0 || index >= count) index = direction === 1 ? -1 : count;
  for (let step = 0; step < count; step += 1) {
    index = ((index + direction) % count + count) % count;
    if (!blocked.has(options[index].username)) return index;
  }
  return -1;
}

/**
 * Searchable single-select profile combobox: type to filter by username or
 * display name, arrow keys to move, Enter to pick, Escape to restore.
 */
export default function ProfilePicker({
  profiles,
  value,
  onChange,
  label,
  showLabel = false,
  caption,
  disabledUsernames,
  placeholder = 'Search profiles...',
  className = '',
}: ProfilePickerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(-1);
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const labelId = useId();
  const inputId = useId();
  const listboxId = useId();
  const optionId = (index: number) => `${listboxId}-option-${index}`;

  const blocked = useMemo(
    () => new Set((disabledUsernames ?? []).filter(Boolean)),
    [disabledUsernames],
  );
  const selected = useMemo(
    () => profiles.find((profile) => profile.username === value),
    [profiles, value],
  );
  const options = useMemo(
    () => profiles.filter((profile) => matchesQuery(profile, query)),
    [profiles, query],
  );

  const closePicker = useCallback((restoreFocus = false) => {
    setIsOpen(false);
    setQuery('');
    setActiveIndex(-1);
    if (restoreFocus) inputRef.current?.focus();
  }, []);

  // Opening always starts from an unfiltered list, so the highlight can be
  // resolved against `profiles` directly.
  const openPicker = useCallback(() => {
    setIsOpen(true);
    setQuery('');
    const selectedIndex = profiles.findIndex((profile) => profile.username === value);
    setActiveIndex(
      selectedIndex >= 0 && !blocked.has(profiles[selectedIndex].username)
        ? selectedIndex
        : nextSelectableIndex(profiles, blocked, -1, 1),
    );
  }, [blocked, profiles, value]);

  const selectProfile = useCallback((profile: ProfileInfo) => {
    if (blocked.has(profile.username)) return;
    onChange(profile.username);
    closePicker(true);
  }, [blocked, closePicker, onChange]);

  useEffect(() => {
    if (!isOpen) return undefined;
    const handlePointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) closePicker();
    };
    document.addEventListener('mousedown', handlePointerDown);
    return () => document.removeEventListener('mousedown', handlePointerDown);
  }, [closePicker, isOpen]);

  useEffect(() => {
    if (!isOpen || activeIndex < 0) return;
    const active = listRef.current?.querySelectorAll('[role="option"]')[activeIndex];
    active?.scrollIntoView({ block: 'nearest' });
  }, [activeIndex, isOpen]);

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (!isOpen) {
        openPicker();
        return;
      }
      setActiveIndex((current) => nextSelectableIndex(
        options,
        blocked,
        current,
        event.key === 'ArrowDown' ? 1 : -1,
      ));
      return;
    }

    if (event.key === 'Home' || event.key === 'End') {
      if (!isOpen) return;
      event.preventDefault();
      setActiveIndex(event.key === 'Home'
        ? nextSelectableIndex(options, blocked, -1, 1)
        : nextSelectableIndex(options, blocked, options.length, -1));
      return;
    }

    if (event.key === 'Enter') {
      if (!isOpen) return;
      event.preventDefault();
      const option = options[activeIndex];
      if (option) selectProfile(option);
      return;
    }

    if (event.key === 'Escape') {
      if (!isOpen) return;
      // Restores the field to the applied selection and keeps the caret here.
      event.preventDefault();
      event.stopPropagation();
      closePicker(true);
      return;
    }

    if (event.key === 'Tab' && isOpen) closePicker();
  };

  const handleQueryChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const nextQuery = event.target.value;
    setQuery(nextQuery);
    setIsOpen(true);
    const nextOptions = profiles.filter((profile) => matchesQuery(profile, nextQuery));
    setActiveIndex(nextSelectableIndex(nextOptions, blocked, -1, 1));
  };

  const trimmedQuery = query.trim();

  return (
    <div ref={rootRef} className={`relative ${className}`}>
      <div
        onClick={() => {
          inputRef.current?.focus();
          if (!isOpen) openPicker();
        }}
        className="block min-w-0 cursor-text rounded-xl border border-white/10 bg-black/20 px-4 py-3 transition-colors hover:border-cinema-400/35 focus-within:border-cinema-400/45"
      >
        <span
          id={labelId}
          className={showLabel ? 'block text-xs font-medium text-white/45' : 'sr-only'}
        >
          {label}
        </span>
        <span className={`flex items-center gap-3 ${showLabel ? 'mt-2' : ''}`}>
          <ProfileAvatar profile={selected} username={value || undefined} size="lg" />
          <span className="min-w-0 flex-1">
            <input
              ref={inputRef}
              id={inputId}
              type="text"
              role="combobox"
              autoComplete="off"
              spellCheck={false}
              aria-labelledby={labelId}
              aria-expanded={isOpen}
              aria-controls={listboxId}
              aria-autocomplete="list"
              aria-activedescendant={isOpen && activeIndex >= 0 ? optionId(activeIndex) : undefined}
              value={isOpen ? query : (selected ? profileLabel(selected) : '')}
              placeholder={isOpen ? placeholder : (value ? `@${value}` : placeholder)}
              onChange={handleQueryChange}
              onFocus={() => { if (!isOpen) openPicker(); }}
              onKeyDown={handleKeyDown}
              className="w-full truncate bg-transparent text-sm font-semibold text-white outline-none placeholder:font-normal placeholder:text-white/35"
            />
            <span className="mt-1 block truncate text-xs text-white/40">
              {caption ?? (selected ? `@${selected.username}` : `${profiles.length} profiles`)}
            </span>
          </span>
          <ChevronDown
            aria-hidden="true"
            className={`h-4 w-4 shrink-0 text-white/45 transition-transform ${isOpen ? 'rotate-180' : ''}`}
          />
        </span>
      </div>

      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.14, ease: 'easeOut' }}
            className="absolute inset-x-0 top-[calc(100%+0.5rem)] z-[100] flex max-h-[min(20rem,calc(100dvh-15rem))] flex-col overflow-clip rounded-xl border border-white/15 bg-[#091525] shadow-2xl shadow-black/60 sm:max-h-80"
          >
            <div className="flex shrink-0 items-center gap-2 border-b border-white/10 px-3 py-2 text-[11px] font-semibold text-white/45">
              <Search className="h-3.5 w-3.5 text-cinema-400" aria-hidden="true" />
              <span>
                {trimmedQuery
                  ? `${options.length} of ${profiles.length} profiles`
                  : `${profiles.length} profile${profiles.length === 1 ? '' : 's'}`}
              </span>
            </div>

            <ul
              ref={listRef}
              id={listboxId}
              role="listbox"
              aria-labelledby={labelId}
              className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-1.5 [scrollbar-gutter:stable]"
            >
              {options.map((profile, index) => {
                const isSelected = profile.username === value;
                const isDisabled = blocked.has(profile.username);
                const isActive = index === activeIndex;
                return (
                  <li
                    key={profile.username}
                    id={optionId(index)}
                    role="option"
                    aria-selected={isSelected}
                    aria-disabled={isDisabled || undefined}
                    onMouseDown={(event) => event.preventDefault()}
                    onMouseEnter={() => { if (!isDisabled) setActiveIndex(index); }}
                    onClick={() => selectProfile(profile)}
                    className={`flex items-center gap-2.5 rounded-lg px-2.5 py-2 transition-colors ${
                      isDisabled
                        ? 'cursor-not-allowed opacity-40'
                        : `cursor-pointer ${isActive ? 'bg-cinema-500/15 ring-1 ring-inset ring-cinema-400/40' : ''}`
                    }`}
                  >
                    <ProfileAvatar profile={profile} size="sm" />
                    <span className="min-w-0 flex-1 leading-tight">
                      <span className="block truncate text-sm font-medium text-white/85">
                        {profileLabel(profile)}
                      </span>
                      <span className="mt-0.5 block truncate text-[11px] text-white/40">
                        @{profile.username}
                      </span>
                    </span>
                    {isSelected && <Check className="h-4 w-4 shrink-0 text-cinema-300" aria-hidden="true" />}
                  </li>
                );
              })}
            </ul>

            {options.length === 0 && (
              <p role="status" className="px-3 pb-4 pt-3 text-center text-xs text-white/35">
                No profiles match {trimmedQuery ? `"${trimmedQuery}"` : 'that search'}.
              </p>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
