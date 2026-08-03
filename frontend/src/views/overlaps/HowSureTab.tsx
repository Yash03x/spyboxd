'use client';

import React from 'react';
import { useQuery } from '@tanstack/react-query';

import Panel from '../../components/terminal/Panel';
import Bars from '../../components/terminal/bodies/Bars';
import Rows, { cell } from '../../components/terminal/bodies/Rows';
import { BarsSkeleton, panelState } from '../../components/terminal/states';
import { useScopedProfiles } from '../../hooks/useScopedProfiles';
import { importTier } from '../../components/terminal/profileState';
import { activityApi, insightsApi, type SurfaceCoverage } from '../../services/api';

function surface(surfaces: SurfaceCoverage[], name: SurfaceCoverage['surface']) {
  return surfaces.find((entry) => entry.surface === name);
}

export default function HowSureTab({ profiles }: { profiles: string[] }) {
  // The same source Overview's roster reads. Deriving the tier from the
  // coverage endpoint's `status` instead put every profile in the middle tier,
  // so this panel reported nobody with a full diary while the roster reported
  // almost everybody -- two panels contradicting each other about the same
  // profiles is worse than either being wrong alone.
  const scopedQuery = useScopedProfiles();

  const coverageQuery = useQuery({
    queryKey: ['data-coverage', profiles],
    queryFn: () => insightsApi.getDataCoverage(profiles),
    enabled: profiles.length > 0,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const lagQuery = useQuery({
    queryKey: ['activity-logging-lag', profiles],
    queryFn: () => activityApi.getLoggingLag(profiles),
    enabled: profiles.length > 0,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const perProfile = React.useMemo(
    () => coverageQuery.data?.profiles ?? [],
    [coverageQuery.data],
  );

  // The three honesty tiers, counted in events rather than profiles: a full
  // diary on a large profile carries far more weight than one on a small one,
  // and the tier a reader cares about is the one behind the row they are
  // looking at.
  const tiers = React.useMemo(() => {
    const byUsername = new Map(
      (scopedQuery.data ?? []).map((profile) => [profile.username.toLowerCase(), profile]),
    );
    let full = 0;
    let onePerFilm = 0;
    let unaccounted = 0;
    perProfile.forEach((entry) => {
      const events = surface(entry.surfaces, 'watch_events');
      const captured = events?.captured ?? 0;
      const expected = events?.expected ?? null;
      const profile = byUsername.get(entry.profile.username.toLowerCase());
      if (profile && importTier(profile) === 'full') {
        full += captured;
      } else {
        onePerFilm += captured;
      }
      if (expected !== null && expected > captured) unaccounted += expected - captured;
    });
    return { full, onePerFilm, unaccounted };
  }, [perProfile, scopedQuery.data]);

  const tierTotal = tiers.full + tiers.onePerFilm + tiers.unaccounted;

  const datedTotal = perProfile.reduce(
    (sum, entry) => sum + (surface(entry.surfaces, 'watch_events')?.captured ?? 0),
    0,
  );
  const expectedTotal = perProfile.reduce(
    (sum, entry) =>
      sum +
      (surface(entry.surfaces, 'watch_events')?.expected ??
        surface(entry.surfaces, 'watch_events')?.captured ??
        0),
    0,
  );

  return (
    <>
      <Panel
        title="HOW SURE WE ARE"
        src="profile_films.source · watch_events"
        blurb="Not every overlap is equally real. A diary row with a date is evidence; a rating snapshot with one inferred date is a guess, and it is labelled as one."
        caveat="Overlaps built on the lower two tiers are shown with the tier named on the row. The bottom tier is the difference between Letterboxd's own stated total and the dated events we hold, so it mixes rows that carry no date with rows we never imported at all — Data › What's missing separates those two."
      >
        {panelState({
          isLoading: coverageQuery.isLoading || scopedQuery.isLoading,
          error: coverageQuery.error ?? scopedQuery.error,
          isEmpty: tierTotal === 0,
          onRetry: () => coverageQuery.refetch(),
          errorTitle: 'Coverage could not be read',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'Nothing imported yet',
            body: 'Coverage tiers describe imported watch history. There is none for this selection.',
          },
          skeleton: <BarsSkeleton rows={3} />,
        }) ?? (
          <Bars
            items={[
              {
                name: 'Full diary imported',
                weight: tiers.full,
                value: tiers.full.toLocaleString(),
                sub: `${Math.round((tiers.full / tierTotal) * 100)}%`,
                tone: 'var(--ok)',
              },
              {
                name: 'One date per film only',
                weight: tiers.onePerFilm,
                value: tiers.onePerFilm.toLocaleString(),
                sub: `${Math.round((tiers.onePerFilm / tierTotal) * 100)}%`,
                tone: 'var(--accent)',
              },
              {
                // Not "no date at all": this is everything Letterboxd counts
                // that we hold no dated event for, which is undated rows and
                // unimported rows together.
                name: 'No dated event',
                weight: tiers.unaccounted,
                value: tiers.unaccounted.toLocaleString(),
                sub: `${Math.round((tiers.unaccounted / tierTotal) * 100)}%`,
                tone: 'var(--barmuted)',
              },
            ]}
          />
        )}
      </Panel>

      <Panel
        title="LOGGING LAG"
        src="watched_date vs logged_date"
        blurb="When they watched it against when they told Letterboxd. Anybody who logs a week late makes same-day overlap detection harder for everybody else."
        caveat={lagQuery.data?.caveat}
      >
        {panelState({
          isLoading: lagQuery.isLoading,
          error: lagQuery.error,
          isEmpty: (lagQuery.data?.measured ?? 0) === 0,
          onRetry: () => lagQuery.refetch(),
          errorTitle: 'Logging lag could not be computed',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No log dates in this selection',
            body: 'A log date exists only in an official Letterboxd export. Public pages publish the watch date and nothing else, so scraped-only profiles cannot appear here at all.',
          },
          skeleton: <BarsSkeleton rows={5} />,
        }) ?? (
          <Bars
            items={(lagQuery.data?.buckets ?? []).map((bucket) => ({
              name: bucket.label,
              weight: bucket.events,
              value: bucket.events.toLocaleString(),
              sub: bucket.share === null ? '' : `${Math.round(bucket.share * 100)}%`,
              tone: bucket.label === 'Same day' ? 'var(--ok)' : 'var(--accent)',
            }))}
          />
        )}
      </Panel>

      <Panel
        title="SHARE CARRYING A REAL DATE"
        src="watch_events.watched_date"
        stats={
          expectedTotal
            ? [
                {
                  big: `${Math.round((datedTotal / expectedTotal) * 100)}%`,
                  unit: 'DATED',
                  tone: 'var(--accent)',
                },
                { big: datedTotal.toLocaleString(), unit: `OF ${expectedTotal.toLocaleString()}` },
              ]
            : undefined
        }
        caveat="Every timing panel in this section is capped by this table. A profile with no dates contributes nothing to Together or Echoes, however large it is."
      >
        {panelState({
          isLoading: coverageQuery.isLoading,
          error: coverageQuery.error,
          isEmpty: perProfile.length === 0,
          onRetry: () => coverageQuery.refetch(),
          errorTitle: 'Per-profile coverage could not be read',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No profiles selected',
            body: 'Choose at least one profile above to see how much of its history carries a date.',
          },
        }) ?? (
          <Rows
            columns="minmax(0,1fr) 62px 62px"
            head={['PROFILE', ['DATED', 'right'], ['SHARE', 'right']]}
            rows={perProfile.map((entry) => {
              const events = surface(entry.surfaces, 'watch_events');
              const captured = events?.captured ?? 0;
              const expected = events?.expected ?? captured;
              const share = expected ? captured / expected : null;
              const tone =
                share === null
                  ? 'var(--muted)'
                  : share >= 0.99
                    ? 'var(--ok)'
                    : share >= 0.6
                      ? 'var(--accent)'
                      : 'var(--bad)';
              return {
                cells: [
                  cell(`@${entry.profile.username}`),
                  cell(captured.toLocaleString(), { align: 'right', tone: 'var(--ink)' }),
                  cell(share === null ? '—' : `${Math.round(share * 100)}%`, {
                    align: 'right',
                    tone,
                  }),
                ],
              };
            })}
          />
        )}
      </Panel>
    </>
  );
}
