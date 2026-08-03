import type { ProfileInfo } from '../../services/api';

/**
 * The three honesty tiers, in one place.
 *
 * Was "authoritative diary" / "legacy rating snapshot", which described our
 * plumbing rather than what the reader gets. Overview's roster and Overlaps ›
 * How sure both classify the same profiles, so they read the same field
 * through the same function — the two panels disagreeing about whether a
 * profile has a full diary is worse than either being wrong on its own.
 */
export type ImportTier = 'full' | 'partial' | 'none' | 'failed';

export function importTier(profile: ProfileInfo): ImportTier {
  const status = profile.scraping_status;
  if (status === 'failed' || status === 'error') return 'failed';
  const coverage = profile.data_coverage;
  if (coverage?.is_partial === false) return 'full';
  if (coverage?.is_partial === true) return 'partial';
  return profile.total_films ? 'partial' : 'none';
}

export const TIER_LABEL: Record<ImportTier, { label: string; tone: string }> = {
  full: { label: 'Full diary imported', tone: 'var(--ok)' },
  partial: { label: 'Recent window only', tone: 'var(--accent)' },
  none: { label: 'Nothing imported yet', tone: 'var(--muted)' },
  failed: { label: 'Nothing since — feed backing off', tone: 'var(--bad)' },
};

export function importState(profile: ProfileInfo): { label: string; tone: string } {
  return TIER_LABEL[importTier(profile)];
}

/**
 * How far back we can see this profile.
 *
 * Letterboxd publishes no join date on a public profile page — it exists only
 * in an account's own export — so a scraped profile used to read "Member since:
 * unknown". The first diary entry answers the same question honestly and we
 * hold it for everyone, so it is preferred and labelled for what it is.
 */
export function sinceLabel(profile: ProfileInfo): { label: string; tone: string } {
  const logged = profile.first_logged_date;
  if (logged) {
    return { label: new Date(logged).getFullYear().toString(), tone: 'var(--muted)' };
  }
  if (profile.join_date) {
    return { label: new Date(profile.join_date).getFullYear().toString(), tone: 'var(--muted)' };
  }
  return { label: 'no dates', tone: 'var(--dim)' };
}
