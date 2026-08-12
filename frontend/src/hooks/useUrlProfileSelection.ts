'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';

interface UrlProfileSelectionOptions {
  isReady: boolean;
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
  const [isInitialized, setIsInitialized] = useState(false);
  const [draftProfiles, setDraftProfiles] = useState<string[]>([]);
  const [appliedProfiles, setAppliedProfiles] = useState<string[]>([]);

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
  }, [availableProfiles, options.defaultCount, options.maxSelection, options.minSelection, urlProfilesKey]);

  // Query-key changes (most importantly the admin scope lens) render before
  // this hook's synchronization effect runs. Reconcile during render as well,
  // so a child query can never receive names from the previous scope in that
  // intervening commit. While the new profile catalog is loading, an empty
  // selection is safer than querying the old scope.
  const reconciledAppliedProfiles = useMemo(() => {
    if (!options.isReady) return [];
    const available = new Set(availableProfiles);
    const valid = appliedProfiles.filter((profile) => available.has(profile));
    const bounded = options.maxSelection ? valid.slice(0, options.maxSelection) : valid;
    return bounded.length >= options.minSelection ? bounded : normalizedProfiles;
  }, [
    appliedProfiles,
    availableProfiles,
    normalizedProfiles,
    options.isReady,
    options.maxSelection,
    options.minSelection,
  ]);

  useEffect(() => {
    if (!options.isReady) return;
    setDraftProfiles((current) => sameProfiles(current, normalizedProfiles) ? current : normalizedProfiles);
    setAppliedProfiles((current) => sameProfiles(current, normalizedProfiles) ? current : normalizedProfiles);
    setIsInitialized(true);
  }, [normalizedProfiles, options.isReady]);

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
  }, [availableProfiles, options.maxSelection, options.minSelection, replaceParams]);

  return {
    appliedProfiles: reconciledAppliedProfiles,
    applyProfiles,
    draftProfiles,
    isInitialized,
    replaceParams,
    setDraftProfiles,
  };
}
