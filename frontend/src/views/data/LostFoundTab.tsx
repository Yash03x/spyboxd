'use client';

import React from 'react';
import { useQuery } from '@tanstack/react-query';

import Panel from '../../components/terminal/Panel';
import { localDate } from '../../components/terminal/dates';
import Notes from '../../components/terminal/bodies/Notes';
import Posters from '../../components/terminal/bodies/Posters';
import Rows, { cell } from '../../components/terminal/bodies/Rows';
import { panelState } from '../../components/terminal/states';
import { sectionHref } from '../../components/terminal/sections';
import { dataHealthApi } from '../../services/api';

const ENTRY_LABEL: Record<string, string> = {
  diary: 'Diary entries',
  review: 'Reviews',
  comment: 'Comments',
  list: 'Lists',
};

const KIND_LABEL: Record<string, string> = {
  deleted: 'the film or thread was removed from Letterboxd',
  orphaned: 'the entry survived but its target could not be resolved',
};

export default function LostFoundTab({
  profiles,
  selectionLoading = false,
}: {
  profiles: string[];
  /** The profile list is still on the wire; an empty selection is not
   *  yet a fact, so a disabled query must not report an absence. */
  selectionLoading?: boolean;
}) {
  const enabled = profiles.length > 0;
  const options = { enabled, staleTime: 5 * 60 * 1000, refetchOnWindowFocus: false };

  const lostQuery = useQuery({
    queryKey: ['data-lost', profiles],
    queryFn: () => dataHealthApi.getLost(profiles),
    ...options,
  });
  const listsQuery = useQuery({
    queryKey: ['data-lost-lists', profiles],
    queryFn: () => dataHealthApi.getLostLists(profiles),
    ...options,
  });

  return (
    <>
      <Panel
        title="DELETED HISTORY WE STILL HOLD"
        src="lost_entries"
        blurb="Diary rows, reviews and comments that exist in an owner export and no longer exist on Letterboxd. History the platform can no longer place."
        caveat={lostQuery.data?.caveat}
      >
        {panelState({
          isLoading: lostQuery.isLoading || (selectionLoading && !enabled),
          error: lostQuery.error,
          isEmpty: (lostQuery.data?.entries.length ?? 0) === 0,
          onRetry: () => lostQuery.refetch(),
          errorTitle: 'The archive could not be read',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No export-only history held',
            body: 'Lost entries come from an official account export. No amount of public scraping reaches them, so a profile that has not supplied one has nothing here.',
            cta: { label: 'HOW TO SUPPLY AN EXPORT', href: sectionHref('data', 'profiles') },
          },
        }) ?? (
          <Rows
            columns="minmax(0,1fr) 66px 84px minmax(0,1.1fr)"
            head={['WHAT', ['ROWS', 'right'], ['OLDEST', 'right'], 'WHY IT WAS LOST']}
            rows={(lostQuery.data?.entries ?? []).map((entry) => ({
              cells: [
                cell(ENTRY_LABEL[entry.entry_type] ?? entry.entry_type, {
                  font: 's',
                  tone: 'var(--ink)',
                }),
                cell(entry.rows.toLocaleString(), { align: 'right', tone: 'var(--accent)' }),
                cell(
                  entry.oldest
                    ? localDate(entry.oldest).toLocaleDateString('en-GB', {
                        month: 'short',
                        year: 'numeric',
                      })
                    : '—',
                  { align: 'right', size: '10px', tone: 'var(--muted)' },
                ),
                cell(KIND_LABEL[entry.lost_kind] ?? entry.lost_kind, {
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
        title="FILMS FROM LISTS THAT NO LONGER EXIST"
        src="list_items × lists.removed_at"
        blurb="A list was deleted, but we still hold what was in it — often the most considered version of somebody's taste, thrown away in a tidy-up."
        caveat={listsQuery.data?.caveat}
      >
        {panelState({
          isLoading: listsQuery.isLoading || (selectionLoading && !enabled),
          error: listsQuery.error,
          isEmpty: (listsQuery.data?.films.length ?? 0) === 0,
          severity: 'quiet',
          onRetry: () => listsQuery.refetch(),
          errorTitle: 'Lost lists could not be read',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No list has disappeared',
            body: 'Nothing in this selection stopped appearing between two reads, so there is nothing to recover.',
          },
        }) ?? (
          <Posters
            items={(listsQuery.data?.films ?? []).slice(0, 8).map((film) => ({
              title: film.year ? `${film.title} (${film.year})` : film.title,
              posterUrl: film.poster_url,
              sub: `from “${film.list_name}” · @${film.username}${
                film.removed_at
                  ? ` · gone ${new Date(film.removed_at).toLocaleDateString('en-GB', { month: 'short', year: 'numeric' })}`
                  : ''
              }`,
              right: `was #${film.position}`,
              tone: 'var(--accent)',
              rightCaption: 'list gone',
            }))}
          />
        )}
      </Panel>

      <Panel title="APPEND-ONLY — WHY ANY OF THIS IS POSSIBLE" src="the storage model itself" wide>
        <Notes
          items={[
            {
              label: 'Absence is not deletion',
              text: 'A row that stops appearing is marked with the date we noticed, never removed. Every panel on this tab is a consequence of that one decision.',
            },
            {
              label: 'A first import proves nothing',
              text: 'One read is a baseline. Change needs two, which is why several panels across the product state what they are waiting for instead of showing an empty table.',
            },
            {
              label: 'The user can still leave',
              text: 'Untracking hides a profile everywhere in the product. Deleting the data is a separate, explicit action, and it is the one thing here that is not reversible.',
            },
          ]}
        />
      </Panel>
    </>
  );
}
