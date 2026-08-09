'use client';

import React from 'react';
import { useQuery } from '@tanstack/react-query';

import Panel from '../../components/terminal/Panel';
import Bars from '../../components/terminal/bodies/Bars';
import Rows, { cell } from '../../components/terminal/bodies/Rows';
import { BarsSkeleton, panelState } from '../../components/terminal/states';
import { sectionHref } from '../../components/terminal/sections';
import { filmsApi } from '../../services/api';

const NEEDS_ENRICHMENT = {
  title: 'TMDB enrichment has not reached this library',
  body: 'Every panel on this tab reads the enrichment cache. Until it fills, there is metadata for nothing here rather than metadata saying nothing.',
  cta: { label: 'SEE THE MATCH RATE', href: sectionHref('films', 'gaps') },
};

/**
 * Filmography runs and worked-through series need a director or a collection
 * with more than one film in it — enrichment can be complete and these still
 * come back empty, so blaming the cache sent the reader to a match-rate page
 * that would tell them everything was fine.
 */
const NEEDS_A_REPEAT = {
  title: 'Nobody here has been watched twice',
  body: 'This counts a director or a series only once the selection has seen more than one of their films. A library of one-offs fills every other panel on this tab and leaves this one empty.',
};

export default function LibraryTab({ profiles }: { profiles: string[] }) {
  const enabled = profiles.length > 0;
  const options = { enabled, staleTime: 5 * 60 * 1000, refetchOnWindowFocus: false };

  const keywordsQuery = useQuery({
    queryKey: ['films-keywords', profiles],
    queryFn: () => filmsApi.getKeywords(profiles),
    ...options,
  });
  const runtimeQuery = useQuery({
    queryKey: ['films-runtime', profiles],
    queryFn: () => filmsApi.getRuntime(profiles),
    ...options,
  });
  const atlasQuery = useQuery({
    queryKey: ['films-atlas', profiles],
    queryFn: () => filmsApi.getAtlas(profiles),
    ...options,
  });
  const filmographyQuery = useQuery({
    queryKey: ['films-filmographies', profiles],
    queryFn: () => filmsApi.getFilmographies(profiles),
    ...options,
  });
  const collectionsQuery = useQuery({
    queryKey: ['films-collections', profiles],
    queryFn: () => filmsApi.getCollections(profiles),
    ...options,
  });

  return (
    <>
      <Panel
        title="SUBJECTS THEY RETURN TO"
        src="movie_enrichments.keywords"
        blurb="Genre says drama. Keywords say grief, one location, unreliable narrator."
        caveat={keywordsQuery.data?.caveat}
      >
        {panelState({
          isLoading: keywordsQuery.isLoading,
          error: keywordsQuery.error,
          isEmpty: (keywordsQuery.data?.keywords.length ?? 0) === 0,
          onRetry: () => keywordsQuery.refetch(),
          errorTitle: 'Keywords could not be read',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: NEEDS_ENRICHMENT,
          skeleton: <BarsSkeleton rows={8} />,
        }) ?? (
          <Bars
            items={(keywordsQuery.data?.keywords ?? []).map((entry) => ({
              name: entry.keyword,
              weight: entry.share,
              value: `${(entry.share * 100).toFixed(1)}%`,
              sub: String(entry.films),
            }))}
          />
        )}
      </Panel>

      <Panel
        title="RUNTIME APPETITE"
        src="enrichments.runtime × watchlist_items"
        blurb="What they add against what they finish. One band is usually where intention and follow-through part company."
        caveat={runtimeQuery.data?.caveat}
      >
        {panelState({
          isLoading: runtimeQuery.isLoading,
          error: runtimeQuery.error,
          isEmpty: (runtimeQuery.data?.bands ?? []).every((band) => band.watched + band.queued === 0),
          onRetry: () => runtimeQuery.refetch(),
          errorTitle: 'Runtime bands could not be read',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: NEEDS_ENRICHMENT,
        }) ?? (
          <Rows
            columns="86px 66px 66px 62px"
            head={['LENGTH', ['WATCHED', 'right'], ['QUEUED', 'right'], ['RATIO', 'right']]}
            rows={(runtimeQuery.data?.bands ?? []).map((band) => ({
              cells: [
                cell(band.label, { size: '10.5px' }),
                cell(band.watched.toLocaleString(), { align: 'right', tone: 'var(--ink)' }),
                cell(band.queued.toLocaleString(), { align: 'right', tone: 'var(--muted)' }),
                // Null rather than infinity: a band nobody has queued has no
                // ratio, and printing one would invent a denominator.
                cell(band.ratio === null ? '—' : `${band.ratio.toFixed(2)}×`, {
                  align: 'right',
                  tone:
                    band.ratio === null
                      ? 'var(--dim)'
                      : band.ratio >= 3
                        ? 'var(--ok)'
                        : band.ratio >= 1.5
                          ? 'var(--ink2)'
                          : 'var(--bad)',
                }),
              ],
            }))}
          />
        )}
      </Panel>

      <Panel
        title="COUNTRIES · AND HOW MUCH READING"
        src="enrichments.production_countries · original_language"
        stats={
          atlasQuery.data
            ? [
                {
                  big:
                    atlasQuery.data.subtitled_share === null
                      ? '—'
                      : `${Math.round(atlasQuery.data.subtitled_share * 100)}%`,
                  unit: 'SUBTITLED',
                  tone: 'var(--accent)',
                },
                { big: atlasQuery.data.distinct_countries, unit: 'COUNTRIES' },
              ]
            : undefined
        }
        caveat={atlasQuery.data?.caveat}
      >
        {panelState({
          isLoading: atlasQuery.isLoading,
          error: atlasQuery.error,
          isEmpty: (atlasQuery.data?.countries.length ?? 0) === 0,
          onRetry: () => atlasQuery.refetch(),
          errorTitle: 'The atlas could not be read',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: NEEDS_ENRICHMENT,
          skeleton: <BarsSkeleton rows={8} />,
        }) ?? (
          <Bars
            items={(atlasQuery.data?.countries ?? []).map((entry, index) => ({
              name: entry.country,
              weight: entry.films,
              value: entry.films.toLocaleString(),
              // The largest country is almost always the reader's own default;
              // muting it stops it swamping the shape of everything else.
              tone: index === 0 ? 'var(--barmuted)' : 'var(--accent)',
            }))}
          />
        )}
      </Panel>

      <Panel
        title="FILMOGRAPHY RUNS"
        isNew
        src="movie_enrichments.credits"
        blurb="How much of one director's work this group holds between them."
        caveat={filmographyQuery.data?.caveat}
      >
        {panelState({
          isLoading: filmographyQuery.isLoading,
          error: filmographyQuery.error,
          isEmpty: (filmographyQuery.data?.directors.length ?? 0) === 0,
          onRetry: () => filmographyQuery.refetch(),
          errorTitle: 'Filmographies could not be read',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: NEEDS_A_REPEAT,
        }) ?? (
          <Rows
            columns="minmax(0,1.1fr) 52px 56px minmax(0,1.2fr)"
            head={['DIRECTOR', ['FILMS', 'right'], ['AVG', 'right'], 'WHAT']}
            rows={(filmographyQuery.data?.directors ?? []).map((director) => ({
              cells: [
                cell(director.director, { font: 's', size: '11.5px', tone: 'var(--ink)' }),
                cell(String(director.films), { align: 'right', tone: 'var(--accent)' }),
                cell(
                  director.average_rating === null ? '—' : director.average_rating.toFixed(1),
                  { align: 'right', tone: director.average_rating === null ? 'var(--dim)' : 'var(--ink2)' },
                ),
                cell(director.titles.slice(0, 3).join(', '), {
                  font: 's',
                  size: '10px',
                  tone: 'var(--dim)',
                  wrap: true,
                }),
              ],
            }))}
          />
        )}
      </Panel>

      <Panel
        title="SERIES WORKED THROUGH"
        src="movie_enrichments.collection"
        blurb="Franchises and collections rather than people. A different question from filmography runs, and often answered very differently."
        caveat={collectionsQuery.data?.caveat}
      >
        {panelState({
          isLoading: collectionsQuery.isLoading,
          error: collectionsQuery.error,
          isEmpty: (collectionsQuery.data?.series.length ?? 0) === 0,
          onRetry: () => collectionsQuery.refetch(),
          errorTitle: 'Series could not be read',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: NEEDS_A_REPEAT,
        }) ?? (
          <Rows
            columns="minmax(0,1fr) 60px 66px"
            head={['SERIES', ['FILMS', 'right'], ['AVG', 'right']]}
            rows={(collectionsQuery.data?.series ?? []).map((series) => ({
              cells: [
                cell(series.name, { font: 's', size: '11.5px', tone: 'var(--ink)' }),
                cell(String(series.films), { align: 'right', tone: 'var(--accent)' }),
                cell(series.average_rating === null ? '—' : series.average_rating.toFixed(1), {
                  align: 'right',
                  tone: series.average_rating === null ? 'var(--dim)' : 'var(--ink2)',
                }),
              ],
            }))}
          />
        )}
      </Panel>
    </>
  );
}
