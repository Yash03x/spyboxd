'use client';

import React from 'react';
import { useQuery } from '@tanstack/react-query';

import Panel from '../../components/terminal/Panel';
import Posters from '../../components/terminal/bodies/Posters';
import Rows, { cell } from '../../components/terminal/bodies/Rows';
import { panelState } from '../../components/terminal/states';
import { filmsApi } from '../../services/api';

export default function GapsTab({ profiles }: { profiles: string[] }) {
  const enabled = profiles.length > 0;
  const options = { enabled, staleTime: 5 * 60 * 1000, refetchOnWindowFocus: false };

  const gapsQuery = useQuery({
    queryKey: ['films-metadata-gaps', profiles],
    queryFn: () => filmsApi.getMetadataGaps(profiles),
    ...options,
  });
  const matchQuery = useQuery({
    queryKey: ['films-match-rate', profiles],
    queryFn: () => filmsApi.getMatchRate(profiles),
    ...options,
  });

  return (
    <>
      <Panel
        title="MISSING METADATA, RANKED BY EXPOSURE"
        src="movies × movie_enrichments"
        blurb="Ordered by how often each film actually appears on screen, not alphabetically. Fixing the top row removes more blank posters than fixing the bottom forty."
        caveat={gapsQuery.data?.caveat}
      >
        {panelState({
          isLoading: gapsQuery.isLoading,
          error: gapsQuery.error,
          isEmpty: (gapsQuery.data?.films.length ?? 0) === 0,
          onRetry: () => gapsQuery.refetch(),
          errorTitle: 'The gap list could not be built',
          errorBody: 'The match-rate panel below is unaffected.',
          empty: {
            title: 'Every film carries metadata',
            body: 'Nothing in this selection is waiting on enrichment. That is the ceiling lifted entirely.',
          },
        }) ?? (
          <Posters
            items={(gapsQuery.data?.films ?? []).map((film) => ({
              title: film.year ? `${film.title} (${film.year})` : film.title,
              // Deliberately drawn as a placeholder rather than hidden: a film
              // with no poster is exactly what this tab is about.
              posterUrl: film.poster_url,
              sub: `in ${film.profiles} profile${film.profiles === 1 ? '' : 's'}`,
              right: `${film.profiles}×`,
              tone: film.profiles >= 4 ? 'var(--bad)' : film.profiles >= 2 ? 'var(--accent)' : 'var(--ink3)',
              rightCaption: film.missing.join(', '),
            }))}
          />
        )}
      </Panel>

      <Panel
        title="MATCH RATE — THE CEILING ON FOUR OTHER TABS"
        src="movies.tmdb_id"
        blurb="Taste breakdown, runtime appetite, countries and availability all read from the enrichment cache. Whatever this number is, it is their maximum."
        stats={
          matchQuery.data
            ? [
                {
                  big:
                    matchQuery.data.ratio === null
                      ? '—'
                      : `${Math.round(matchQuery.data.ratio * 100)}%`,
                  unit: 'MATCHED',
                  tone: 'var(--accent)',
                },
                {
                  big: matchQuery.data.enriched.toLocaleString(),
                  unit: `OF ${matchQuery.data.films.toLocaleString()}`,
                },
              ]
            : undefined
        }
        caveat={matchQuery.data?.caveat}
      >
        {panelState({
          isLoading: matchQuery.isLoading,
          error: matchQuery.error,
          isEmpty: (matchQuery.data?.films ?? 0) === 0,
          onRetry: () => matchQuery.refetch(),
          errorTitle: 'The match rate could not be read',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: { title: 'Nothing imported yet', body: 'There is no library to match against.' },
        }) ?? (
          <Rows
            columns="minmax(0,1fr) 74px"
            rows={(matchQuery.data?.reasons ?? []).map((reason) => ({
              cells: [
                cell(reason.reason, { font: 's', size: '10.5px', tone: 'var(--ink3)', wrap: true }),
                cell(reason.films.toLocaleString(), { align: 'right', tone: 'var(--ink)' }),
              ],
            }))}
          />
        )}
      </Panel>
    </>
  );
}
