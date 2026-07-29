'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';

interface UrlProfileSelectionOptions {
  minSelection: number;
  maxSelection?: number;
  defaultCount: number;
}

interface ApplyOptions {
  params?: Record<string, string | null | undefined>;
  scroll?: boolean;
}

function sameProfiles(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((profile, index) => profile === right[index]);
}

export function useUrlProfileSelection(
  availableProfiles: string[],
  options: UrlProfileSelectionOptions,
) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialized = useRef(false);
  const [draftProfiles, setDraftProfiles] = useState<string[]>([]);
  const [appliedProfiles, setAppliedProfiles] = useState<string[]>([]);

  const availableKey = availableProfiles.join('\u0000');
  const urlProfilesKey = searchParams.getAll('profiles').join('\u0001');
  const normalizedProfiles = useMemo(() => {
    const profileMap = new Map(
      availableProfiles.map((profile) => [profile.toLocaleLowerCase(), profile]),
    );
    const requested = (urlProfilesKey ? urlProfilesKey.split('\u0001') : [])
      .flatMap((value) => value.split(','))
      .map((value) => profileMap.get(value.trim().toLocaleLowerCase()))
      .filter((value): value is string => Boolean(value));
    const deduped = Array.from(new Set(requested));
    const bounded = options.maxSelection ? deduped.slice(0, options.maxSelection) : deduped;

    if (bounded.length >= options.minSelection) return bounded;
    return availableProfiles.slice(0, options.defaultCount);
  }, [availableKey, availableProfiles, options.defaultCount, options.maxSelection, options.minSelection, urlProfilesKey]);

  useEffect(() => {
    if (availableProfiles.length < options.minSelection) return;
    setDraftProfiles((current) => sameProfiles(current, normalizedProfiles) ? current : normalizedProfiles);
    setAppliedProfiles((current) => sameProfiles(current, normalizedProfiles) ? current : normalizedProfiles);
    initialized.current = true;
  }, [availableKey, availableProfiles.length, normalizedProfiles, options.minSelection, urlProfilesKey]);

  const replaceParams = useCallback((
    profiles: string[],
    extraParams: Record<string, string | null | undefined> = {},
    scroll = false,
  ) => {
    const params = new URLSearchParams(searchParams.toString());
    params.delete('profiles');
    profiles.forEach((profile) => params.append('profiles', profile));
    Object.entries(extraParams).forEach(([key, value]) => {
      if (value === null || value === undefined || value === '') params.delete(key);
      else params.set(key, value);
    });
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll });
  }, [pathname, router, searchParams]);

  const applyProfiles = useCallback((profiles: string[], applyOptions: ApplyOptions = {}) => {
    const deduped = Array.from(new Set(profiles.filter((profile) => availableProfiles.includes(profile))));
    const bounded = options.maxSelection ? deduped.slice(0, options.maxSelection) : deduped;
    if (bounded.length < options.minSelection) return false;
    setDraftProfiles(bounded);
    setAppliedProfiles((current) => sameProfiles(current, bounded) ? current : bounded);
    replaceParams(bounded, applyOptions.params, applyOptions.scroll);
    return true;
  }, [availableKey, availableProfiles, options.maxSelection, options.minSelection, replaceParams]);

  return {
    appliedProfiles,
    applyProfiles,
    draftProfiles,
    isInitialized: initialized.current,
    replaceParams,
    setDraftProfiles,
  };
}
