'use client';

import React from 'react';
import { useQuery } from '@tanstack/react-query';

import Panel from '../../components/terminal/Panel';
import Diverge from '../../components/terminal/bodies/Diverge';
import Posters from '../../components/terminal/bodies/Posters';
import Quads from '../../components/terminal/bodies/Quads';
import Rows, { cell } from '../../components/terminal/bodies/Rows';
import Spark from '../../components/terminal/bodies/Spark';
import { panelState } from '../../components/terminal/states';
import { sectionHref } from '../../components/terminal/sections';
import { filmsApi, watchlistInsightsApi } from '../../services/api';

const QUAD_TONES = ['var(--ok)', 'var(--accent)', 'var(--blue)', 'var(--muted)'];

function yearsSince(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '—';
  const months = Math.round((Date.now() - then) / (1000 * 60 * 60 * 24 * 30.44));
  return `${Math.floor(months / 12)}y ${months % 12}m`;
}

export default function TasteMapTab({ profiles }: { profiles: string[] }) {
  const enabled = profiles.length > 0;
  const options = { enabled, staleTime: 5 * 60 * 1000, refetchOnWindowFocus: false };

  const quadrantsQuery = useQuery({
    queryKey: ['films-liked-vs-rated', profiles],
    queryFn: () => filmsApi.getLikedVsRated(profiles),
    ...options,
  });
  const divergenceQuery = useQuery({
    queryKey: ['films-decade-divergence', profiles],
    queryFn: () => filmsApi.getDecadeDivergence(profiles),
    ...options,
  });
  const queueAgeQuery = useQuery({
    queryKey: ['films-queue-age', profiles],
    queryFn: () => filmsApi.getQueueAge(profiles),
    ...options,
  });
  const ladderQuery = useQuery({
    queryKey: ['films-language-ladder', profiles],
    queryFn: () => filmsApi.getLanguageLadder(profiles),
    ...options,
  });
  const conversionQuery = useQuery({
    queryKey: ['watchlist-insights', profiles[0]],
    queryFn: () => watchlistInsightsApi.getInsights(profiles[0]),
    enabled: profiles.length > 0,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  return (
    <>
      <Panel
        title="LOVED IT, RATED IT, BOTH, NEITHER"
        src="profile_films.is_liked × rating"
        blurb="A heart and a score are different instruments. The interesting corner is the third one: films given four stars with the heart withheld."
        caveat={quadrantsQuery.data?.caveat}
      >
        {panelState({
          isLoading: quadrantsQuery.isLoading,
          error: quadrantsQuery.error,
          isEmpty: (quadrantsQuery.data?.total ?? 0) === 0,
          onRetry: () => quadrantsQuery.refetch(),
          errorTitle: 'The quadrants could not be computed',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: { title: 'Nothing imported yet', body: 'Neither instrument has been used here.' },
        }) ?? (
          <Quads
            items={(quadrantsQuery.data?.quadrants ?? []).map((quad, index) => ({
              tag: quad.tag,
              n: quad.films.toLocaleString(),
              pct: `${Math.round(quad.share * 100)}%`,
              note: quad.note,
              tone: QUAD_TONES[index] ?? 'var(--muted)',
            }))}
          />
        )}
      </Panel>

      <Panel
        title="WHERE THEY PART WITH THE CROWD"
        isNew
        src="ratings × crowd avg by movies.release_year"
        blurb="Divergence from consensus, split by the film's decade. A single contrarian number hides this: somebody can be conventional about new releases and heretical about the seventies."
        caveat={divergenceQuery.data?.caveat}
      >
        {panelState({
          isLoading: divergenceQuery.isLoading,
          error: divergenceQuery.error,
          isEmpty: (divergenceQuery.data?.decades.length ?? 0) === 0,
          onRetry: () => divergenceQuery.refetch(),
          errorTitle: 'Divergence could not be computed',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No decade has enough compared films',
            body: "This needs Letterboxd's own crowd average on a rated film. Decades with fewer than five such films are dropped rather than shown as a lean built from two opinions.",
          },
        }) ?? (
          <Diverge
            label="DECADE"
            axis="HARSHER ← → KINDER"
            items={(divergenceQuery.data?.decades ?? []).map((entry) => ({
              name: entry.decade,
              value: entry.delta,
              n: entry.films,
            }))}
          />
        )}
      </Panel>

      <Panel
        title="QUEUE CONVERSION"
        src="watchlist_items × profile_films"
        blurb="How much of what gets added actually gets watched."
        stats={
          conversionQuery.data
            ? [
                {
                  big: conversionQuery.data.coverage.watchlist_films.toLocaleString(),
                  unit: 'STILL QUEUED',
                  tone: 'var(--accent)',
                },
                {
                  big: conversionQuery.data.coverage.rated_by_group.toLocaleString(),
                  unit: 'RATED BY SOMEBODY TRACKED',
                },
              ]
            : undefined
        }
        caveat="The queue holds unwatched films only, so a converted entry leaves it entirely. This is what is still waiting, not a conversion rate over all time — nothing records when something left."
      >
        {panelState({
          isLoading: conversionQuery.isLoading,
          error: conversionQuery.error,
          isEmpty: (conversionQuery.data?.coverage.watchlist_films ?? 0) === 0,
          onRetry: () => conversionQuery.refetch(),
          errorTitle: 'Queue conversion could not be read',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'Nothing waiting in the queue',
            body: 'Either the watchlist is private, or everything on it has been watched.',
          },
        }) ?? (
          <Rows
            columns="minmax(0,1fr) 76px 76px"
            head={['LONGEST WAITING', ['ADDED', 'right'], ['WAITING', 'right']]}
            rows={(conversionQuery.data?.longest_waiting ?? []).slice(0, 6).map((film) => ({
              cells: [
                cell(film.year ? `${film.title} (${film.year})` : film.title, {
                  font: 's',
                  size: '10.5px',
                  wrap: true,
                }),
                cell(
                  film.added_date
                    ? new Date(film.added_date).toLocaleDateString('en-GB', {
                        month: 'short',
                        year: 'numeric',
                      })
                    : 'no date',
                  { align: 'right', size: '10px', tone: 'var(--muted)' },
                ),
                // An unknown wait, not a zero-day one.
                cell(film.days_waiting === null ? '—' : `${Math.round(film.days_waiting / 365)}y`, {
                  align: 'right',
                  tone: film.days_waiting === null ? 'var(--dim)' : 'var(--accent)',
                }),
              ],
            }))}
          />
        )}
      </Panel>

      <Panel
        title="OLDEST IN THE QUEUE"
        isNew
        src="watchlist_items.added_date"
        blurb="Entries that have survived every refresh since they were added."
        caveat={queueAgeQuery.data?.caveat}
      >
        {panelState({
          isLoading: queueAgeQuery.isLoading,
          error: queueAgeQuery.error,
          isEmpty: (queueAgeQuery.data?.films.length ?? 0) === 0,
          onRetry: () => queueAgeQuery.refetch(),
          errorTitle: 'Queue age could not be computed',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No queue entry carries an added date',
            body: 'The added date comes from an official export only. A scraped watchlist has an order and no dates, so nothing here can be aged.',
            cta: { label: 'HOW TO SUPPLY AN EXPORT', href: sectionHref('data', 'profiles') },
          },
        }) ?? (
          <Posters
            items={(queueAgeQuery.data?.films ?? []).slice(0, 6).map((film) => ({
              title: film.year ? `${film.title} (${film.year})` : film.title,
              posterUrl: film.poster_url,
              sub: `@${film.username} · added ${new Date(film.added_date).toLocaleDateString('en-GB', { month: 'short', year: 'numeric' })}`,
              right: yearsSince(film.added_date),
              tone: 'var(--accent)',
              rightCaption: 'still waiting',
            }))}
          />
        )}
      </Panel>

      <Panel
        title="LANGUAGE LADDER"
        isNew
        src="enrichments.original_language × year"
        blurb="Non-English share, year over year. Somebody widening their range looks nothing like somebody who always watched this way, and a current ratio cannot tell them apart."
        caveat={ladderQuery.data?.caveat}
      >
        {panelState({
          isLoading: ladderQuery.isLoading,
          error: ladderQuery.error,
          isEmpty: (ladderQuery.data?.years.length ?? 0) === 0,
          onRetry: () => ladderQuery.refetch(),
          errorTitle: 'The language ladder could not be computed',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No year has enough enriched watches',
            body: 'This needs a dated watch whose film carries an original language. Years with fewer than ten are dropped rather than shown as a share built from a handful.',
          },
        }) ?? (
          <Spark
            items={(ladderQuery.data?.years ?? []).map((entry) => ({
              label: String(entry.year).slice(2),
              value: Math.round(entry.share * 100),
              display: `${Math.round(entry.share * 100)}%`,
              hint: `${entry.year}: ${entry.non_english} of ${entry.watches} watches were not in English`,
            }))}
            max={100}
          />
        )}
      </Panel>
    </>
  );
}
