'use client';

import React from 'react';
import { useQuery } from '@tanstack/react-query';

import Panel from '../../components/terminal/Panel';
import Notes from '../../components/terminal/bodies/Notes';
import Posters from '../../components/terminal/bodies/Posters';
import Rows, { cell } from '../../components/terminal/bodies/Rows';
import { panelState } from '../../components/terminal/states';
import { sectionHref } from '../../components/terminal/sections';
import { insightsApi, tonightApi, type WatchTogetherCandidate } from '../../services/api';
import type { PickPreferences } from './PickFilters';
import RecommendationEvaluation from './RecommendationEvaluation';

function availabilityLabel(candidate: WatchTogetherCandidate, region: string, compact = false): string {
  const offers = candidate.movie.providers;
  const label = (type: string) => {
    const names = [...new Set(offers.filter((offer) => offer.type === type).map((offer) => offer.name))];
    const limit = compact ? 2 : 5;
    return `${names.slice(0, limit).join(', ')}${names.length > limit ? ` +${names.length - limit} more` : ''}`;
  };
  const subscription = label('flatrate');
  const rent = label('rent');
  const buy = label('buy');
  const health = candidate.movie.availability_health;
  const location = region === 'ALL' ? 'supported countries' : region;
  const summary = compact && subscription ? `${subscription} (subscription)` : [subscription && `${subscription} (subscription)`, rent && `${rent} (rent)`, buy && `${buy} (buy)`].filter(Boolean).join('; ');
  if (!summary) return health?.status === 'fresh' ? `No recorded offers in ${location}` : `Availability not verified in ${location}`;
  return `${summary}${health?.status === 'stale' ? ' · stale — confirm offers' : health?.status !== 'fresh' ? ' · read date unknown' : ''}`;
}

export default function PicksTab({
  profiles,
  region,
  pick,
  pickHref,
  preferences,
  resetHref,
}: {
  profiles: string[];
  region: string;
  /** Which shortlist row the explanation panel is unpacking. */
  pick: string | null;
  pickHref: (title: string) => string;
  preferences: PickPreferences;
  resetHref: string;
}) {
  const ready = profiles.length >= 2;

  const shortlistQuery = useQuery({
    queryKey: ['watch-together', profiles, region, preferences],
    queryFn: () =>
      insightsApi.getWatchTogether(profiles, { mode: 'watchlist_overlap', region, ...preferences }),
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
  const hasFilters = Boolean(preferences.maxRuntime || preferences.genre || preferences.availability || preferences.rewatch === 'unseen');
  const coverageMessages = [...new Set([
    ...(shortlistQuery.data?.coverage.blockers ?? []),
    ...(shortlistQuery.data?.coverage.warnings ?? []),
  ])];
  // The explanation unpacks whichever row was chosen, defaulting to the top.
  // Heading it "why this ranked first" for a row the reader clicked was the
  // old panel's one dishonest sentence.
  const top =
    candidates.find(
      (candidate) => String(candidate.movie.movie_id) === pick,
    ) ?? candidates.find(
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
        blurb={`Ranked across the selected group's watchlists, with equal influence per person. ${preferences.rewatch === 'unseen' ? 'Only films nobody in the group has logged are included.' : 'Rewatches are welcome; SEEN tells you how many people would be rewatching.'}`}
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
                {
                  big: candidates
                    .filter((candidate) => candidate.on_watchlist_by.length === profiles.length)
                    .length.toLocaleString(),
                  unit: "ON EVERYONE'S WATCHLIST",
                },
                {
                  big: candidates
                    .filter((candidate) => candidate.watched_by.length === 0)
                    .length.toLocaleString(),
                  unit: 'NOBODY HAS SEEN',
                },
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
          `Fit is a ranking score, not a predicted rating. Compare it only with other films for this same group and filter selection.` +
          (summary && summary.candidates > candidates.length
            ? ` ${summary.candidates.toLocaleString()} candidates cleared the filters; the ${candidates.length.toLocaleString()} below are the best fits, and the count above is the length of this table.`
            : ` Every ranked candidate is rendered below — the count above is the length of this table, not a larger set it was cut from.`)
        }
      >
        {coverageMessages.length ? (
          <div role="status" className="border-b border-term-rule px-[10px] py-3 font-term-sans text-t11 text-term-ink3">
            <strong className="text-term-accent">Some recommendations have limited evidence</strong>
            <ul className="mb-0 mt-2 list-disc space-y-1 pl-4">{coverageMessages.map((message) => <li key={message}>{message}</li>)}</ul>
          </div>
        ) : null}
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
            ? hasFilters ? {
                title: 'No films match these filters',
                body: 'Try a longer runtime, another genre or watch option, or allow rewatches. Missing data may also limit the matches; check the coverage notes above.',
                cta: { label: 'CLEAR FILTERS', href: resetHref },
              } : {
                title: 'Nothing on the selected watchlists yet',
                // This mode ranks whatever is queued -- it never filters to
                // films nobody has seen, and the region only decides where a
                // film can be watched, not whether it is listed. Saying
                // otherwise sent people to change a control that could not
                // help.
                body: 'This ranks films somebody in the room has queued, seen or not. Nobody in the selection has a watchlist entry we hold, so there is nothing to rank.',
                cta: { label: 'CHECK WATCHLIST COVERAGE', href: sectionHref('data', 'missing') },
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
              return {
                href: pickHref(String(candidate.movie.movie_id ?? candidate.movie.title)),
                cells: [
                  cell(
                    candidate.movie.year
                      ? `${candidate.movie.title} (${candidate.movie.year})`
                      : candidate.movie.title,
                    {
                      font: 's',
                      size: '11.5px',
                      tone:
                        candidate === top
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
                    availabilityLabel(candidate, region, true),
                    {
                      font: 's',
                      size: '10px',
                      tone: candidate.movie.availability_health?.status === 'stale' ? 'var(--accent)' : 'var(--ink3)',
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
        blurb="Choose profiles above to change the group. Baseline reads below are separate from recent RSS updates; unread history is not proof that someone has never seen a film."
        caveat={
          shortlistQuery.data
            ? `Recommendation data: ${shortlistQuery.data.coverage.status}. ${shortlistQuery.data.coverage.blockers.join(' ')}`
            : undefined
        }
      >
        <Rows
          columns="minmax(0,1fr) minmax(0,1.6fr)"
          head={['IN THE ROOM', 'DATA COVERAGE']}
          rows={profiles.map((username) => ({
            cells: [
              cell(`@${username}`),
              cell(shortlistQuery.data?.profile_coverage?.find((entry) => entry.username === username)?.surfaces.map((surface) =>
                `${surface.surface}: ${surface.status}${surface.last_updated ? ` · read ${new Date(surface.last_updated).toLocaleDateString('en-GB')}` : ' · date unknown'}`
              ).join('; ') || 'Coverage has not been verified', { size: '10px', tone: 'var(--muted)', wrap: true }),
            ],
          }))}
        />
        <RecommendationEvaluation profiles={profiles} />
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
                  : 'No recorded watch among the selected profiles. Viewing that was never logged is unknown.',
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
                text: `${availabilityLabel(top!, region)}.${top!.movie.availability_health?.checked_at ? ` Checked ${new Date(top!.movie.availability_health.checked_at).toLocaleDateString('en-GB')}.` : ''}${region === 'ALL' ? ' Worldwide means an offer exists in at least one supported country, not necessarily yours.' : ''}`,
              },
              {
                label: 'How the group score works',
                text: top!.score_breakdown
                  ? `Shared watchlists: ${top!.score_breakdown.watchlist}/40; new to the group: ${top!.score_breakdown.unseen}/25; balanced ratings: ${top!.score_breakdown.ratings}/25; rating evidence: ${top!.score_breakdown.evidence}/10. ${top!.score_breakdown.rated_members} of ${top!.score_breakdown.members} people have rated it. Every person counts equally; unknown ratings are neutral, and the lowest member rating tempers the average. This is a transparent ranking heuristic, not a prediction of everyone's taste.`
                  : 'The score ranks evidence held for this group; it is not a predicted star rating.',
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
        blurb="A top rating from one person that nobody else in the room has logged. These are separate discoveries, not filtered shortlist results."
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
