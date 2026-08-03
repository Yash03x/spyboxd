'use client';

import React from 'react';
import { useQuery } from '@tanstack/react-query';

import Panel from '../../components/terminal/Panel';
import Bars from '../../components/terminal/bodies/Bars';
import Posters from '../../components/terminal/bodies/Posters';
import Rows, { cell } from '../../components/terminal/bodies/Rows';
import { BarsSkeleton, panelState } from '../../components/terminal/states';
import { insightsApi, tonightApi } from '../../services/api';

export default function ListsTab({ profiles }: { profiles: string[] }) {
  const enabled = profiles.length > 0;
  const options = { enabled, staleTime: 5 * 60 * 1000, refetchOnWindowFocus: false };

  const listsQuery = useQuery({
    queryKey: ['public-lists', profiles],
    queryFn: () => insightsApi.getPublicLists(profiles),
    ...options,
  });
  const progressQuery = useQuery({
    queryKey: ['tonight-list-progress', profiles],
    queryFn: () => tonightApi.getListProgress(profiles),
    ...options,
  });
  const listOnlyQuery = useQuery({
    queryKey: ['tonight-list-only', profiles],
    queryFn: () => tonightApi.getListOnlyFilms(profiles),
    ...options,
  });
  const cadenceQuery = useQuery({
    queryKey: ['tonight-list-cadence', profiles],
    queryFn: () => tonightApi.getListCadence(profiles),
    ...options,
  });

  return (
    <>
      <Panel
        title="WORK THROUGH A LIST"
        src="lists × list_items × profile_films"
        blurb="Was “list mission”. Every public list the group can see, with how much of it is imported."
        caveat={
          listsQuery.data
            ? `${listsQuery.data.summary.available_lists.toLocaleString()} public ${listsQuery.data.summary.available_lists === 1 ? 'list holds' : 'lists hold'} ${listsQuery.data.summary.total_movie_items.toLocaleString()} entries. A private list cannot be counted at all, so an absence here is not a list nobody started.`
            : undefined
        }
      >
        {panelState({
          isLoading: listsQuery.isLoading,
          error: listsQuery.error,
          isEmpty: (listsQuery.data?.lists.length ?? 0) === 0,
          severity: 'quiet',
          onRetry: () => listsQuery.refetch(),
          errorTitle: 'Public lists could not be loaded',
          errorBody: 'The other Tonight modes are still available; only this panel is affected.',
          empty: {
            title: 'No readable list',
            body: 'Nobody in the selection has a public list we have imported.',
          },
        }) ?? (
          <Rows
            columns="minmax(0,1.3fr) 70px minmax(0,0.7fr)"
            head={['LIST', ['FILMS', 'right'], 'OWNER']}
            rows={(listsQuery.data?.lists ?? []).slice(0, 8).map((list) => ({
              cells: [
                cell(list.name, { font: 's', size: '11px', tone: 'var(--ink)', wrap: true }),
                cell(list.movie_count.toLocaleString(), { align: 'right', tone: 'var(--ink)' }),
                cell(`@${list.owner}`, { size: '10px', tone: 'var(--muted)' }),
              ],
            }))}
          />
        )}
      </Panel>

      <Panel
        title="HOW FAR THE GROUP HAS GOT"
        src="list_items × profile_films"
        blurb="Any watch by any selected profile counts. The interesting number is not the percentage but how many people it took to get there."
        caveat={progressQuery.data?.caveat}
      >
        {panelState({
          isLoading: progressQuery.isLoading,
          error: progressQuery.error,
          isEmpty: (progressQuery.data?.lists.length ?? 0) === 0,
          onRetry: () => progressQuery.refetch(),
          errorTitle: 'List progress could not be computed',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No readable list to measure',
            body: 'A private list cannot be counted, so there is nothing to be part-way through.',
          },
          skeleton: <BarsSkeleton rows={5} />,
        }) ?? (
          <Bars
            items={(progressQuery.data?.lists ?? []).map((list) => ({
              name: list.name,
              weight: list.share ?? 0,
              value: list.share === null ? '—' : `${Math.round(list.share * 100)}%`,
              sub: `${list.contributors} ${list.contributors === 1 ? 'person' : 'people'}`,
            }))}
            max={1}
          />
        )}
      </Panel>

      <Panel
        title="ON EVERY LIST, ON NOBODY'S DIARY"
        src="list_items × profile_films absence"
        blurb="Films that appear across several lists the group follows and that nobody has watched. Canonical blind spots rather than obscure ones."
        caveat={listOnlyQuery.data?.caveat}
      >
        {panelState({
          isLoading: listOnlyQuery.isLoading,
          error: listOnlyQuery.error,
          isEmpty: (listOnlyQuery.data?.films.length ?? 0) === 0,
          onRetry: () => listOnlyQuery.refetch(),
          errorTitle: 'List-only films could not be computed',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No canonical blind spot',
            // Two different absences, and the old copy asserted the second
            // whichever one was true.
            body:
              (listsQuery.data?.summary.available_lists ?? 0) < 2
                ? 'A canonical blind spot needs a film on two of the selection’s own public lists, and there are fewer than two to cross. Nothing has been watched or missed here yet.'
                : 'Everything on two or more of those lists has been watched by somebody in the selection.',
          },
        }) ?? (
          <Posters
            items={(listOnlyQuery.data?.films ?? []).slice(0, 6).map((film) => ({
              title: film.year ? `${film.title} (${film.year})` : film.title,
              posterUrl: film.poster_url,
              href: film.letterboxd_url ?? undefined,
              sub: `on ${film.lists} lists · 0 watches${film.queued ? ' · queued by somebody' : ''}`,
              right: `${film.lists} lists`,
              tone: film.lists >= 3 ? 'var(--accent)' : 'var(--ink3)',
              rightCaption: 'blind spot',
            }))}
          />
        )}
      </Panel>

      <Panel
        title="WHO KEEPS THEIR LISTS ALIVE"
        src="lists.updated_at"
        blurb="A list last touched years ago is a document; one edited last week is a plan. Only the second is worth ranking against."
        caveat={cadenceQuery.data?.caveat}
      >
        {panelState({
          isLoading: cadenceQuery.isLoading,
          error: cadenceQuery.error,
          isEmpty: (cadenceQuery.data?.profiles.length ?? 0) === 0,
          onRetry: () => cadenceQuery.refetch(),
          errorTitle: 'List cadence could not be computed',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: { title: 'No profiles selected', body: 'Choose at least one profile above.' },
        }) ?? (
          <Rows
            columns="minmax(0,1fr) 52px 62px 80px minmax(0,1fr)"
            // SHOWN is the count the other three panels on this tab work from.
            // Without it a profile reading "16 lists" here beside "1 readable
            // list" above looks like one of the two is broken.
            head={['PROFILE', ['LISTS', 'right'], ['SHOWN', 'right'], ['LAST EDIT', 'right'], 'READ']}
            rows={(cadenceQuery.data?.profiles ?? []).map((entry) => {
              const tone =
                entry.lists === 0
                  ? 'var(--muted)'
                  : entry.last_edit_days === null
                    ? 'var(--dim)'
                    : entry.last_edit_days <= 30
                      ? 'var(--ok)'
                      : entry.last_edit_days <= 180
                        ? 'var(--accent)'
                        : 'var(--bad)';
              return {
                cells: [
                  cell(`@${entry.username}`),
                  cell(String(entry.lists), { align: 'right', tone: 'var(--ink)' }),
                  cell(String(entry.public_lists), {
                    align: 'right',
                    size: '10px',
                    tone: entry.public_lists < entry.lists ? 'var(--accent)' : 'var(--muted)',
                  }),
                  cell(
                    entry.last_edit_days === null ? '—' : `${entry.last_edit_days}d ago`,
                    { align: 'right', size: '10px', tone: 'var(--muted)' },
                  ),
                  cell(entry.read, { font: 's', size: '10px', tone, wrap: true }),
                ],
              };
            })}
          />
        )}
      </Panel>
    </>
  );
}
