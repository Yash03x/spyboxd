'use client';

import React from 'react';
import { useQuery } from '@tanstack/react-query';

import Panel from '../../components/terminal/Panel';
import Notes from '../../components/terminal/bodies/Notes';
import Posters from '../../components/terminal/bodies/Posters';
import Rows, { cell } from '../../components/terminal/bodies/Rows';
import { panelState } from '../../components/terminal/states';
import { sectionHref } from '../../components/terminal/sections';
import {
  insightsApi,
  tonightApi,
  type WatchTogetherCandidate,
  type WatchTogetherMode,
} from '../../services/api';

export type TonightPickMode = Exclude<WatchTogetherMode, 'list_mission'>;

const MODE_COPY: Record<
  TonightPickMode,
  { blurb: string; empty: { title: string; body: string } }
> = {
  watchlist_overlap: {
    blurb:
      'Ranked by fit across whoever is in the room. Want is how many have it queued; seen is how many have already watched it and are being asked to rewatch.',
    empty: {
      title: 'Nothing on the selected watchlists yet',
      body: 'This ranks films somebody in the room has queued, seen or not. Nobody in the selection has a watchlist entry we hold, so there is nothing to rank.',
    },
  },
  unseen_pick: {
    blurb:
      'Only films nobody in the room has watched. Selected watchlists supply intent; ratings from other accessible profiles can supply evidence that the film is worth the risk.',
    empty: {
      title: 'No unseen group pick found',
      body: 'Nothing backed by the selected watchlists or accessible rating evidence is still unseen by everybody in the room.',
    },
  },
  collective_blind_spots: {
    blurb:
      'One person in the room liked it or rated it at least four stars, and everybody else selected has yet to see it. A personal favourite becomes a group recommendation.',
    empty: {
      title: 'No one-person favourite to pass around',
      body: 'No film is liked or rated at least four stars by exactly one person in the room while remaining unseen by everybody else selected.',
    },
  },
};

function decisionStats(
  mode: TonightPickMode,
  candidates: WatchTogetherCandidate[],
  profileCount: number,
) {
  if (mode === 'unseen_pick') {
    return [
      {
        big: candidates.filter((candidate) => candidate.on_watchlist_by.length > 0).length.toLocaleString(),
        unit: 'ON A SELECTED WATCHLIST',
      },
      {
        big: candidates.filter((candidate) => candidate.watched_by.length === 0).length.toLocaleString(),
        unit: 'UNSEEN BY THE ROOM',
      },
    ];
  }
  if (mode === 'collective_blind_spots') {
    return [
      {
        big: candidates.filter((candidate) => candidate.blind_spot_source).length.toLocaleString(),
        unit: 'BACKED BY ONE PERSON',
      },
      {
        big: candidates
          .filter((candidate) => candidate.unseen_by.length === profileCount - 1)
          .length.toLocaleString(),
        unit: 'NEW TO EVERYONE ELSE',
      },
    ];
  }
  return [
    {
      big: candidates
        .filter((candidate) => candidate.on_watchlist_by.length === profileCount)
        .length.toLocaleString(),
      unit: "ON EVERYONE'S WATCHLIST",
    },
    {
      big: candidates.filter((candidate) => candidate.watched_by.length === 0).length.toLocaleString(),
      unit: 'NOBODY HAS SEEN',
    },
  ];
}

export default function PicksTab({
  profiles,
  region,
  mode,
  pick,
  pickHref,
}: {
  profiles: string[];
  region: string;
  mode: TonightPickMode;
  /** Which shortlist row the explanation panel is unpacking. */
  pick: string | null;
  pickHref: (title: string) => string;
}) {
  const ready = profiles.length >= 2;

  const shortlistQuery = useQuery({
    queryKey: ['watch-together', profiles, region, mode],
    queryFn: () =>
      insightsApi.getWatchTogether(profiles, { mode, region }),
    enabled: ready,
    staleTime: 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const blindSpotsQuery = useQuery({
    queryKey: ['tonight-blind-spot-favourites', profiles],
    queryFn: () => tonightApi.getBlindSpotFavourites(profiles),
    enabled: ready,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const candidates = shortlistQuery.data?.recommendations ?? [];
  const summary = shortlistQuery.data?.summary;
  const modeCopy = MODE_COPY[mode];
  // The explanation unpacks whichever row was chosen, defaulting to the top.
  // Heading it "why this ranked first" for a row the reader clicked was the
  // old panel's one dishonest sentence.
  const top =
    candidates.find(
      (candidate) => candidate.movie.title.toLowerCase() === (pick ?? '').toLowerCase(),
    ) ?? candidates[0];

  const needsTwo = {
    title: 'Two people are needed',
    body: 'A group pick is a film that suits more than one person. With one profile in the room there is nothing to reconcile.',
    cta: { label: 'CHOOSE WHO TO MONITOR', href: sectionHref('data', 'profiles') },
  };

  return (
    <>
      <Panel
        title="TONIGHT'S SHORTLIST"
        src="watchlist_items × profile_films × ratings"
        wide
        blurb={modeCopy.blurb}
        // Counted from the rows actually rendered rather than from the
        // server's summary. A header claiming more candidates than the table
        // below it holds is the one thing this panel must never do, and
        // deriving the count from the same array makes that structural.
        stats={
          candidates.length
            ? [
                {
                  big: candidates.length.toLocaleString(),
                  unit: 'RANKED CANDIDATES',
                  tone: 'var(--accent)',
                },
                ...decisionStats(mode, candidates, profiles.length),
                {
                  // Subscription only, matching what Tonight › Leaving soon
                  // counts. The payload carries rent and buy offers too, and
                  // counting those called a film you must pay for twice
                  // "streaming" — while the other tab, on the same data,
                  // disagreed.
                  big: candidates
                    .filter((candidate) =>
                      candidate.movie.providers.some((provider) => provider.type === 'flatrate'),
                    )
                    .length.toLocaleString(),
                  unit: `ON A SUBSCRIPTION IN ${region}`,
                },
              ]
            : undefined
        }
        caveat={
          // summary.candidates is now counted before the server's cut, so the
          // two branches are finally distinguishable — the old copy claimed
          // "never cut from a larger set" against a total computed after the
          // cut, which could not disagree with the table it annotated.
          `Fit was “group fit score”. It is a rank, not a rating — the number only means something against the other rows in this table.` +
          (summary && summary.candidates > candidates.length
            ? ` ${summary.candidates.toLocaleString()} candidates cleared the filters; the ${candidates.length.toLocaleString()} below are the best fits, and the count above is the length of this table.`
            : ` Every ranked candidate is rendered below — the count above is the length of this table, not a larger set it was cut from.`)
        }
      >
        {panelState({
          isLoading: shortlistQuery.isLoading,
          error: shortlistQuery.error,
          isEmpty: !ready || candidates.length === 0,
          severity: 'fatal',
          errorTitle: 'Group picks could not be loaded',
          errorBody:
            'The request failed. Adjust the selection or the region and try again — the message from the API is shown rather than an empty result.',
          onRetry: () => shortlistQuery.refetch(),
          empty: ready
            ? {
                ...modeCopy.empty,
                cta: { label: 'CHECK INPUT COVERAGE', href: sectionHref('data', 'missing') },
              }
            : needsTwo,
        }) ?? (
          <Rows
            columns="minmax(0,1.4fr) 54px 62px 52px 52px minmax(0,1.1fr)"
            head={[
              'FILM',
              ['FIT', 'right'],
              ['WANT', 'right'],
              ['SEEN', 'right'],
              ['MINS', 'right'],
              'WHERE',
            ]}
            rows={candidates.map((candidate) => {
              const wanted = candidate.on_watchlist_by.length;
              const seen = candidate.watched_by.length;
              // Subscription offers first and named as such; rent/buy are
              // real answers to "where can we watch this" but they are not
              // the same answer, and the panel used to merge them silently.
              const streaming = candidate.movie.providers
                .filter((provider) => provider.type === 'flatrate')
                .map((provider) => provider.name);
              const payToWatch = candidate.movie.providers
                .filter((provider) => provider.type !== 'flatrate')
                .map((provider) => provider.name);
              const providers = streaming.length
                ? streaming
                : payToWatch.length
                  ? [`${payToWatch.join(', ')} (rent or buy)`]
                  : [];
              // A film TMDB never matched has no provider row to be absent
              // from, so "not carried" would be a checked negative we never
              // checked.
              const providersKnown = candidate.movie.tmdb_id !== null
                && candidate.movie.tmdb_id !== undefined;
              return {
                href: pickHref(candidate.movie.title),
                cells: [
                  cell(
                    candidate.movie.year
                      ? `${candidate.movie.title} (${candidate.movie.year})`
                      : candidate.movie.title,
                    {
                      font: 's',
                      size: '11.5px',
                      tone:
                        candidate.movie.title === top?.movie.title
                          ? 'var(--accent)'
                          : 'var(--ink)',
                    },
                  ),
                  cell(candidate.group_fit_score.toFixed(0), {
                    align: 'right',
                    tone: 'var(--ok)',
                  }),
                  cell(`${wanted} of ${profiles.length}`, {
                    align: 'right',
                    size: '10px',
                    tone: 'var(--muted)',
                  }),
                  cell(String(seen), { align: 'right', size: '10px', tone: 'var(--muted)' }),
                  cell(
                    candidate.movie.runtime_minutes === null
                      ? '—'
                      : String(candidate.movie.runtime_minutes),
                    { align: 'right', size: '10px', tone: 'var(--muted)' },
                  ),
                  // "Not carried in this region" -- never "not streamable
                  // anywhere", which the provider feed cannot tell us.
                  cell(
                    providers.length
                      ? providers.join(', ')
                      : providersKnown
                        ? `not carried in ${region}`
                        : 'never looked up',
                    {
                      font: 's',
                      size: '10px',
                      tone: providers.length ? 'var(--ink3)' : 'var(--dim)',
                      wrap: true,
                    },
                  ),
                ],
              };
            })}
          />
        )}
      </Panel>

      <Panel
        title="WHO IS IN THE ROOM"
        src="session filters"
        blurb="Everything on this tab recomputes from this row, including which films count as nobody's-seen-it."
        caveat={
          shortlistQuery.data
            ? `${shortlistQuery.data.coverage.blockers.length ? shortlistQuery.data.coverage.blockers.join(' ') : 'Every selected profile has an imported watchlist.'}`
            : undefined
        }
      >
        <Rows
          columns="minmax(0,1fr) minmax(0,1fr)"
          head={['IN THE ROOM', 'REGION']}
          rows={profiles.map((username, index) => ({
            cells: [
              cell(`@${username}`),
              cell(index === 0 ? region : '', { size: '10px', tone: 'var(--muted)' }),
            ],
          }))}
        />
      </Panel>

      <Panel
        title={top ? `WHY ${top.movie.title.toUpperCase()} FITS` : 'WHY THIS ONE FITS'}
        src="the row above, unpacked"
        blurb={
          top
            ? `Click any row above to unpack it. Every claim traces to a table, and where the evidence is thin the panel says so.`
            : 'Click any row above to unpack it.'
        }
      >
        {panelState({
          isLoading: shortlistQuery.isLoading,
          error: shortlistQuery.error,
          isEmpty: !top,
          onRetry: () => shortlistQuery.refetch(),
          errorTitle: 'The explanation could not be built',
          errorBody: 'The shortlist above is the same request; if it loaded, retry here.',
          empty: ready
            ? { title: 'Nothing to explain yet', body: 'The shortlist is empty, so there is no top row to unpack.' }
            : needsTwo,
        }) ?? (
          <Notes
            items={[
              {
                label: `${top!.on_watchlist_by.length} of ${profiles.length} already want it`,
                text: top!.on_watchlist_by.length
                  ? `Queued by ${top!.on_watchlist_by.map((name) => `@${name}`).join(', ')}.`
                  : 'Nobody has it queued — it is here on the strength of who has not seen it rather than who asked for it.',
              },
              {
                label: `${top!.watched_by.length} in the room have seen it`,
                text: top!.watched_by.length
                  ? `${top!.watched_by.map((name) => `@${name}`).join(', ')} would be rewatching.`
                  : 'A genuine first for everybody in the room rather than a rewatch for one.',
              },
              {
                label: 'Who has seen it, and who it is new to',
                text: top!.unseen_by.length
                  ? `New to ${top!.unseen_by.map((name) => `@${name}`).join(', ')}${
                      top!.watched_by.length
                        ? `; already seen by ${top!.watched_by.map((name) => `@${name}`).join(', ')}.`
                        : '.'
                    }`
                  : 'Everybody in the room has already seen it, so this is a rewatch for all of them.',
              },
              {
                label: 'Where it can be watched',
                text: top!.movie.providers.length
                  ? `${top!.movie.providers.map((provider) => provider.name).join(', ')} in ${region}, as of the last provider reading.`
                  : `Not carried by a subscription service in ${region} at the last reading. That is a fact about ${region}, not about the film.`,
              },
              {
                label: 'How sure the fit is',
                text: top!.reasons.length
                  ? `Fit is a rank across the selected room, not a rating. ${top!.reasons
                      .map((reason) => (reason.endsWith('.') ? reason : `${reason}.`))
                      .join(' ')}`
                  : 'Fit is a rank across the selected room, not a rating: it only means something against the other rows in the table above.',
              },
            ]}
          />
        )}
      </Panel>

      <Panel
        title="FAVOURITES NOBODY ELSE HAS SEEN"
        src="ratings × profile_films absence"
        blurb="A top rating from one person that nobody else in the room has logged. The strongest recommendation the data holds."
        caveat={blindSpotsQuery.data?.caveat}
      >
        {panelState({
          isLoading: blindSpotsQuery.isLoading,
          error: blindSpotsQuery.error,
          isEmpty: !ready || (blindSpotsQuery.data?.films.length ?? 0) === 0,
          onRetry: () => blindSpotsQuery.refetch(),
          errorTitle: 'Blind-spot favourites could not be computed',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: ready
            ? {
                title: 'No unshared favourite',
                body: 'Everything one person loves, somebody else in the room has already logged. An unrated film cannot qualify however much they liked it.',
              }
            : needsTwo,
        }) ?? (
          <Posters
            items={(blindSpotsQuery.data?.films ?? []).slice(0, 6).map((film) => ({
              title: film.year ? `${film.title} (${film.year})` : film.title,
              posterUrl: film.poster_url,
              href: film.letterboxd_url ?? undefined,
              sub: `@${film.username} · ${film.rating.toFixed(1)}★ · nobody else logged it`,
              right: film.rating.toFixed(1),
              tone: 'var(--ok)',
              rightCaption: `0 of ${film.unseen_by} seen`,
            }))}
          />
        )}
      </Panel>
    </>
  );
}
