'use client';

import React from 'react';
import { useQuery } from '@tanstack/react-query';

import Panel from '../../components/terminal/Panel';
import Bars from '../../components/terminal/bodies/Bars';
import Diverge from '../../components/terminal/bodies/Diverge';
import Notes from '../../components/terminal/bodies/Notes';
import Posters from '../../components/terminal/bodies/Posters';
import Rows, { cell } from '../../components/terminal/bodies/Rows';
import Spark from '../../components/terminal/bodies/Spark';
import SpoilerReviewText from '../../components/SpoilerReviewText';
import { BarsSkeleton, panelState } from '../../components/terminal/states';
import { sectionHref } from '../../components/terminal/sections';
import {
  insightsApi,
  peopleApi,
  type PairMovieComparison,
  type TasteTimelinePoint,
} from '../../services/api';

/**
 * An average is only as good as what it rests on. Where rated events and total
 * watches differ, both are named — and where they are the same, the denominator
 * is dropped rather than repeated as a redundant second number.
 */
function periodSummary(point: TasteTimelinePoint, username: string): string {
  const own = point.per_profile.find((entry) => entry.username === username);
  if (!own || own.watch_events === 0) return '—';
  const average = own.average_rating === null ? '—' : `${own.average_rating.toFixed(2)} avg`;
  if (own.rated_events && own.rated_events !== own.watch_events) {
    return `${average} of ${own.rated_events} rated · ${own.watch_events} watches`;
  }
  return `${average} · ${own.watch_events} watches`;
}

function ratingFor(comparison: PairMovieComparison, username: string): number | null {
  return comparison.observations.find((entry) => entry.username === username)?.rating ?? null;
}

const NEED_TWO = {
  title: 'Two people are needed',
  body: 'This tab compares one history against another. Select a second profile above and every panel fills in.',
  cta: { label: 'CHOOSE WHO TO MONITOR', href: sectionHref('data', 'profiles') },
};

export default function TwoPeopleTab({ profiles }: { profiles: string[] }) {
  const pair = profiles.slice(0, 2);
  const [left, right] = pair;
  const ready = pair.length === 2;

  const dossierQuery = useQuery({
    queryKey: ['pair-dossier', pair],
    queryFn: () => insightsApi.getPairDossier(pair, 3),
    enabled: ready,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const dnaQuery = useQuery({
    queryKey: ['taste-dna', pair],
    queryFn: () => insightsApi.getTasteDna(pair),
    enabled: ready,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const timelineQuery = useQuery({
    queryKey: ['taste-timeline', pair],
    queryFn: () => insightsApi.getTasteTimeline(pair),
    enabled: ready,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const tagsQuery = useQuery({
    queryKey: ['people-tag-overlap', pair],
    queryFn: () => peopleApi.getTagOverlap(pair),
    enabled: ready,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const driftQuery = useQuery({
    queryKey: ['people-decade-drift', pair],
    queryFn: () => peopleApi.getDecadeDrift(pair),
    enabled: ready,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const blindSpotsQuery = useQuery({
    queryKey: ['people-pair-blind-spots', pair],
    queryFn: () => peopleApi.getPairBlindSpots(pair),
    enabled: ready,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const reviewsQuery = useQuery({
    queryKey: ['people-reviews-per-watch', pair],
    queryFn: () => peopleApi.getReviewsPerWatch(pair),
    enabled: ready,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const dossier = dossierQuery.data;
  const summary = dossier?.summary;

  // A face-off needs prose on both sides. Where only one of them wrote, that
  // single review is still worth showing -- as a spotlight, labelled for what
  // it is, rather than dropped for failing to be a face-off.
  const written = [...(dossier?.disagreements ?? []), ...(dossier?.agreements ?? [])].filter(
    (comparison) => comparison.observations.some((observation) => Boolean(observation.review_text)),
  );
  const faceOff =
    written.find((comparison) =>
      comparison.observations.every((observation) => Boolean(observation.review_text)),
    ) ?? written[0];
  const isFaceOff = Boolean(
    faceOff?.observations.every((observation) => Boolean(observation.review_text)),
  );

  const genreDimension = dnaQuery.data?.dimensions.genre ?? [];

  const drift = driftQuery.data?.profiles ?? {};

  return (
    <>
      <Panel
        title={ready ? `HEAD TO HEAD — @${left.toUpperCase()} vs @${right.toUpperCase()}` : 'HEAD TO HEAD'}
        src="ratings × profile_films"
        blurb="Was the pair dossier. The two columns are the same measures side by side; the third says what the difference means."
        caveat={
          summary
            ? `Agreement is the average distance between their stars on ${summary.rated_overlap.toLocaleString()} films both have rated. Half a star or less is the threshold worth calling agreement.`
            : undefined
        }
      >
        {panelState({
          isLoading: dossierQuery.isLoading,
          error: dossierQuery.error,
          isEmpty: !ready || !summary,
          severity: 'fatal',
          errorTitle: 'This comparison could not be loaded',
          errorBody: 'The pair endpoint did not answer.',
          onRetry: () => dossierQuery.refetch(),
          empty: NEED_TWO,
        }) ?? (
          <Rows
            columns="minmax(0,1.1fr) 66px 66px minmax(0,1fr)"
            head={[
              'MEASURE',
              [left.slice(0, 8).toUpperCase(), 'right'],
              [right.slice(0, 8).toUpperCase(), 'right'],
              'READ',
            ]}
            rows={[
              {
                measure: 'Shared films',
                a: summary!.shared_titles.toLocaleString(),
                b: summary!.shared_titles.toLocaleString(),
                read: 'Both have logged these',
              },
              {
                measure: 'Both rated',
                a: summary!.rated_overlap.toLocaleString(),
                b: summary!.rated_overlap.toLocaleString(),
                read: 'The only films a gap can be measured on',
              },
              {
                measure: 'Agree within',
                a: summary!.average_rating_gap !== null ? `${summary!.average_rating_gap.toFixed(2)}★` : '—',
                b: summary!.average_rating_gap !== null ? `${summary!.average_rating_gap.toFixed(2)}★` : '—',
                read:
                  summary!.average_rating_gap !== null && summary!.average_rating_gap <= 0.5
                    ? 'Well inside half a star'
                    : 'Wider than half a star',
              },
              {
                measure: 'Same day',
                a: summary!.same_day_events.toLocaleString(),
                b: summary!.same_day_events.toLocaleString(),
                read: `Counted, not dropped: ${summary!.same_day_events.toLocaleString()} landed on the same day, where neither of them was first`,
              },
              {
                measure: 'Gets there first',
                a: summary!.lead.leader === left ? `${Math.round((summary!.lead.lead_share ?? 0) * 100)}%` : '—',
                b: summary!.lead.leader === right ? `${Math.round((summary!.lead.lead_share ?? 0) * 100)}%` : '—',
                read:
                  summary!.lead.beats_volume === null
                    ? 'Not enough dated films to say'
                    : summary!.lead.beats_volume
                      ? `Above the ${Math.round((summary!.lead.expected_share ?? 0) * 100)}% their watch volume alone would produce, so they genuinely get there earlier`
                      : `At or below the ${Math.round((summary!.lead.expected_share ?? 0) * 100)}% their watch volume alone would produce, so this is volume rather than leading`,
              },
              {
                measure: 'Decided by a date',
                a: summary!.lead.decided_films.toLocaleString(),
                b: summary!.lead.decided_films.toLocaleString(),
                read: `${summary!.lead.decided_films.toLocaleString()} films they both dated, days apart — the only ones a lead can be read from`,
              },
            ].map((row) => ({
              cells: [
                cell(row.measure, { font: 's' }),
                cell(row.a, { align: 'right', tone: 'var(--ink)' }),
                cell(row.b, { align: 'right', tone: 'var(--ink)' }),
                cell(row.read, { font: 's', size: '10px', tone: 'var(--dim)', wrap: true }),
              ],
            }))}
          />
        )}
      </Panel>

      <Panel
        title="TASTE BREAKDOWN, SIDE BY SIDE"
        src="movie_enrichments.genres"
        blurb="Where the two diverge is the whole point of the panel — the bar is the group score, the number beside it the sample it was built from."
        caveat={
          dnaQuery.data
            ? `Similarity ${dnaQuery.data.summary.similarity_score?.toFixed(1) ?? '—'}, but ${dnaQuery.data.summary.crowd_adjusted_similarity?.toFixed(1) ?? '—'} once Letterboxd's own average is subtracted from both sides. The gap between those two is agreement with the crowd rather than with each other.`
            : undefined
        }
      >
        {panelState({
          isLoading: dnaQuery.isLoading,
          error: dnaQuery.error,
          isEmpty: !ready || genreDimension.length === 0,
          onRetry: () => dnaQuery.refetch(),
          errorTitle: 'Taste breakdown could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: ready
            ? {
                title: 'No metadata dimensions are ready yet',
                body: 'TMDB enrichment has not reached enough of these two libraries.',
                cta: { label: 'SEE THE MATCH RATE', href: sectionHref('films', 'gaps') },
              }
            : NEED_TWO,
          skeleton: <BarsSkeleton rows={8} />,
        }) ?? (
          <Bars
            items={genreDimension.slice(0, 8).map((trait) => ({
              name: trait.label,
              weight: trait.group_score,
              value: trait.group_score.toFixed(0),
              sub: `${trait.sample_size}`,
            }))}
          />
        )}
      </Panel>

      <Panel
        title="HOW TASTE CHANGED"
        src="ratings × year"
        blurb="Both averages by year, plotted as the distance between them. Convergence is the interesting shape."
        caveat={
          timelineQuery.data
            ? `Shown in hundredths of a star across ${timelineQuery.data.summary.years} years. ${timelineQuery.data.summary.undated_known_watches.toLocaleString()} known watches carry no date and sit in no year at all.`
            : undefined
        }
      >
        {panelState({
          isLoading: timelineQuery.isLoading,
          error: timelineQuery.error,
          isEmpty: !ready || (timelineQuery.data?.yearly.length ?? 0) === 0,
          onRetry: () => timelineQuery.refetch(),
          errorTitle: 'The timeline could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: ready
            ? { title: 'No dated periods', body: 'Neither profile has dated rated events to plot.' }
            : NEED_TWO,
        }) ?? (
          <>
          <Spark
            items={(timelineQuery.data?.yearly ?? []).map((point) => {
              const a = point.per_profile.find((entry) => entry.username === left)?.average_rating;
              const b = point.per_profile.find((entry) => entry.username === right)?.average_rating;
              const distance = a !== null && a !== undefined && b !== null && b !== undefined
                ? Math.abs(a - b)
                : 0;
              return {
                label: String(point.year).slice(2),
                value: Math.round(distance * 100),
                display: distance ? distance.toFixed(2) : '—',
                hint: `${point.label}: ${a?.toFixed(2) ?? '—'} against ${b?.toFixed(2) ?? '—'}`,
              };
            })}
          />
          <Rows
            columns="56px minmax(0,1fr) minmax(0,1fr)"
            head={['PERIOD', [`@${left ?? ''}`, 'right'], [`@${right ?? ''}`, 'right']]}
            rows={(timelineQuery.data?.yearly ?? []).slice(-6).map((point) => ({
              cells: [
                cell(point.label, { size: '10.5px', tone: 'var(--ink3)' }),
                cell(periodSummary(point, left), {
                  align: 'right',
                  size: '10px',
                  tone: 'var(--ink2)',
                }),
                cell(periodSummary(point, right), {
                  align: 'right',
                  size: '10px',
                  tone: 'var(--ink2)',
                }),
              ],
            }))}
          />
          </>
        )}
      </Panel>

      <Panel
        title="TAGS THEY BOTH USE"
        src="profile_films.tags"
        blurb="Private vocabulary, independently invented. Overlapping tags are the strongest soft signal of a shared frame of reference in the whole schema."
        caveat={tagsQuery.data?.caveat}
      >
        {panelState({
          isLoading: tagsQuery.isLoading,
          error: tagsQuery.error,
          isEmpty: !ready || (tagsQuery.data?.tags.length ?? 0) === 0,
          onRetry: () => tagsQuery.refetch(),
          errorTitle: 'Tag overlap could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: ready
            ? {
                title: 'No tag in common',
                body: 'Either they share no vocabulary, or one of them was last read by an importer that did not collect tags — which is not the same as using none.',
                cta: { label: 'SEE WHICH IMPORTER READ THEM', href: sectionHref('data', 'refreshes') },
              }
            : NEED_TWO,
          skeleton: <BarsSkeleton rows={5} />,
        }) ?? (
          <Bars
            items={(tagsQuery.data?.tags ?? []).map((entry) => ({
              name: entry.tag,
              weight: entry.total,
              value: entry.total.toLocaleString(),
              sub: pair.map((name) => entry.counts[name] ?? 0).join(' / '),
            }))}
          />
        )}
      </Panel>

      <Panel
        title="WHICH WAY EACH IS DRIFTING"
        src="movies.release_year × watched_date"
        blurb="Average release year of what each watched, per year of watching. One of them may be walking backwards through film history."
        caveat={driftQuery.data?.caveat}
      >
        {panelState({
          isLoading: driftQuery.isLoading,
          error: driftQuery.error,
          isEmpty: !ready || Object.values(drift).every((points) => points.length === 0),
          onRetry: () => driftQuery.refetch(),
          errorTitle: 'Drift could not be computed',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: ready
            ? {
                title: 'No dated watches with a release year',
                body: 'Films with no release year are excluded rather than dated to the present.',
              }
            : NEED_TWO,
        }) ?? (
          <Rows
            columns="60px minmax(0,1fr) minmax(0,1fr)"
            head={[
              'YEAR',
              [`@${left ?? ''}`, 'right'],
              [`@${right ?? ''}`, 'right'],
            ]}
            rows={Array.from(
              new Set(Object.values(drift).flatMap((points) => points.map((point) => point.year))),
            )
              .sort((a, b) => b - a)
              .slice(0, 8)
              .map((year) => {
                const a = drift[left]?.find((point) => point.year === year);
                const b = drift[right]?.find((point) => point.year === year);
                return {
                  cells: [
                    cell(String(year), { size: '10.5px', tone: 'var(--ink3)' }),
                    cell(a ? `${a.average_release_year.toFixed(0)} · ${a.films} films` : '—', {
                      align: 'right',
                      size: '10.5px',
                      tone: 'var(--ink2)',
                    }),
                    cell(b ? `${b.average_release_year.toFixed(0)} · ${b.films} films` : '—', {
                      align: 'right',
                      size: '10.5px',
                      tone: 'var(--ink2)',
                    }),
                  ],
                };
              })}
          />
        )}
      </Panel>

      <Panel
        title="COMMON LOVES"
        src="ratings both high"
        blurb="Films they both rated at the top of their scale. The shortest possible answer to what these two have in common."
      >
        {panelState({
          isLoading: dossierQuery.isLoading,
          error: dossierQuery.error,
          isEmpty: !ready || (dossier?.agreements.length ?? 0) === 0,
          onRetry: () => dossierQuery.refetch(),
          errorTitle: 'Agreements could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: ready
            ? {
                title: 'Not enough shared ratings yet',
                body: 'Both profiles need a rating on the same film before it can appear here.',
              }
            : NEED_TWO,
        }) ?? (
          <Posters
            items={(dossier?.agreements ?? []).slice(0, 6).map((comparison) => ({
              title: comparison.movie.year
                ? `${comparison.movie.title} (${comparison.movie.year})`
                : comparison.movie.title,
              posterUrl: comparison.movie.poster_url,
              href: comparison.movie.letterboxd_url ?? undefined,
              sub: comparison.observations
                .map((entry) => `@${entry.username} ${entry.rating?.toFixed(1) ?? '—'}`)
                .join(' · '),
              right: comparison.rating_gap === null ? '—' : comparison.rating_gap.toFixed(1),
              tone: 'var(--ok)',
              rightCaption: 'star gap',
            }))}
          />
        )}
      </Panel>

      <Panel
        title="BIGGEST DISAGREEMENTS"
        src="ratings gap on shared films"
        blurb="Ordered by distance, not by who is right."
      >
        {panelState({
          isLoading: dossierQuery.isLoading,
          error: dossierQuery.error,
          isEmpty: !ready || (dossier?.disagreements.length ?? 0) === 0,
          onRetry: () => dossierQuery.refetch(),
          errorTitle: 'Disagreements could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: ready
            ? {
                title: 'Nothing they disagree about',
                body: 'Every film both have rated lands within the same half-star.',
              }
            : NEED_TWO,
        }) ?? (
          <Rows
            columns="minmax(0,1fr) 46px 46px 52px"
            head={[
              'FILM',
              [left?.slice(0, 5).toUpperCase() ?? 'A', 'right'],
              [right?.slice(0, 5).toUpperCase() ?? 'B', 'right'],
              ['GAP', 'right'],
            ]}
            rows={(dossier?.disagreements ?? []).slice(0, 8).map((comparison) => {
              const gap = comparison.rating_gap ?? 0;
              return {
                cells: [
                  cell(comparison.movie.title, { font: 's', tone: 'var(--ink)', wrap: true }),
                  cell(ratingFor(comparison, left)?.toFixed(1) ?? '—', {
                    align: 'right',
                    tone: 'var(--ink2)',
                  }),
                  cell(ratingFor(comparison, right)?.toFixed(1) ?? '—', {
                    align: 'right',
                    tone: 'var(--ink2)',
                  }),
                  cell(gap.toFixed(1), {
                    align: 'right',
                    tone: gap >= 1.5 ? 'var(--bad)' : 'var(--accent)',
                  }),
                ],
              };
            })}
          />
        )}
      </Panel>

      <Panel
        title={isFaceOff ? 'THE SAME FILM, BOTH REVIEWS' : 'THE SAME FILM, ONE REVIEW'}
        src="reviews on a shared film"
        blurb={
          faceOff
            ? `${faceOff.movie.title} — one of their widest gaps, with what ${
                isFaceOff ? 'each of them' : 'the one who wrote'
              } actually said.`
            : 'A film they both wrote about, with each review beside the other.'
        }
        caveat="Spoiler-flagged text stays collapsed until asked for. That flag is the author's own, not our guess."
      >
        {panelState({
          isLoading: dossierQuery.isLoading,
          error: dossierQuery.error,
          isEmpty: !ready || !faceOff,
          onRetry: () => dossierQuery.refetch(),
          errorTitle: 'The review face-off could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: ready
            ? {
                title: 'Neither of them wrote about a shared film',
                body: 'This needs prose on at least one side of a film they both rated.',
              }
            : NEED_TWO,
        }) ?? (
          <Notes
            items={(faceOff?.observations ?? []).map((observation) => ({
              label: `@${observation.username} · ${observation.rating?.toFixed(1) ?? '—'}★${
                observation.contains_spoilers ? ' · spoilers' : ''
              }${observation.review_text ? '' : ' · no written review'}`,
              text: (
                <SpoilerReviewText
                  text={observation.review_text ?? 'No written review'}
                  containsSpoilers={observation.contains_spoilers}
                  reviewLabel={`${observation.username}'s review of ${faceOff?.movie.title}${
                    faceOff?.movie.year ? ` (${faceOff.movie.year})` : ''
                  }`}
                />
              ),
            }))}
          />
        )}
      </Panel>

      <Panel
        title="STRONGEST SHARED AFFINITIES"
        src="movie_enrichments.keywords"
        blurb="What they over-index on together against the rest of the tracked group, with how often each one is actually liked. Below the bars: the films that put them there."
      >
        {panelState({
          isLoading: dnaQuery.isLoading,
          error: dnaQuery.error,
          isEmpty: !ready || (dnaQuery.data?.shared_signature.length ?? 0) === 0,
          onRetry: () => dnaQuery.refetch(),
          errorTitle: 'Shared affinities could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: ready
            ? {
                title: 'Nothing they share strongly enough to name',
                body: 'A shared signature needs enough enriched films on both sides to beat the group baseline.',
              }
            : NEED_TWO,
          skeleton: <BarsSkeleton rows={5} />,
        }) ?? (
            <>
              <Bars
                items={(dnaQuery.data?.shared_signature ?? []).slice(0, 8).map((trait) => ({
                  name: trait.label,
                  weight: trait.group_score,
                  // Two traits can score the same and be liked at wildly
                  // different rates; the score alone cannot separate them. A
                  // trait with nothing liked yet has no rate, not a rate of 0%.
                  value:
                    trait.like_rate === null
                      ? '— liked'
                      : `${Math.round(trait.like_rate * 100)}% liked`,
                  sub: `of ${trait.sample_size}`,
                  tone: 'var(--ok)',
                }))}
              />
              {(dnaQuery.data?.semantic_neighbors?.length ?? 0) > 0 ? (
                <Posters
                  items={(dnaQuery.data?.semantic_neighbors ?? []).slice(0, 4).map((neighbor) => ({
                    title: neighbor.movie.year
                      ? `${neighbor.movie.title} (${neighbor.movie.year})`
                      : neighbor.movie.title,
                    posterUrl: neighbor.movie.poster_url,
                    sub: neighbor.reason,
                    right: neighbor.watched_by.map((name) => `@${name}`).join(' + '),
                    tone: 'var(--ink3)',
                    rightCaption:
                      neighbor.day_gap === null ? 'no date on one side' : `${neighbor.day_gap} days apart`,
                  }))}
                />
              ) : null}
            </>
        )}
      </Panel>

      <Panel
        title="NEITHER HAS SEEN IT"
        src="circle ratings × both watch absence"
        blurb="Films the rest of the circle rates highly that neither of these two has logged. A pair-level blind spot, which is a better shortlist than either watchlist."
        caveat={blindSpotsQuery.data?.caveat}
      >
        {panelState({
          isLoading: blindSpotsQuery.isLoading,
          error: blindSpotsQuery.error,
          isEmpty: !ready || (blindSpotsQuery.data?.films.length ?? 0) === 0,
          onRetry: () => blindSpotsQuery.refetch(),
          errorTitle: 'Blind spots could not be computed',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: ready
            ? {
                title: 'No blind spot to show',
                body: 'Between them they have seen everything the rest of the circle rates highly, or there is no third profile to learn from yet.',
                cta: { label: 'CHOOSE WHO TO MONITOR', href: sectionHref('data', 'profiles') },
              }
            : NEED_TWO,
        }) ?? (
          <Posters
            items={(blindSpotsQuery.data?.films ?? []).slice(0, 6).map((film) => ({
              title: film.year ? `${film.title} (${film.year})` : film.title,
              posterUrl: film.poster_url,
              href: film.letterboxd_url ?? undefined,
              sub: `${film.rater_count} in their circle · avg ${film.average_rating.toFixed(1)}`,
              right: film.average_rating.toFixed(1),
              tone: film.average_rating >= 4.4 ? 'var(--ok)' : 'var(--accent)',
              rightCaption: 'neither seen',
            }))}
          />
        )}
      </Panel>

      <Panel
        title="REVIEWS PER WATCH"
        isNew
        src="reviews ÷ profile_films"
        blurb="How often watching turns into writing. Separates the diarist from the critic without reading a word of anybody's prose."
        caveat={reviewsQuery.data?.caveat}
      >
        {panelState({
          isLoading: reviewsQuery.isLoading,
          error: reviewsQuery.error,
          isEmpty: !ready || (reviewsQuery.data?.profiles.length ?? 0) === 0,
          onRetry: () => reviewsQuery.refetch(),
          errorTitle: 'Reviews per watch could not be computed',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: NEED_TWO,
          skeleton: <BarsSkeleton rows={2} />,
        }) ?? (
          <Bars
            items={(reviewsQuery.data?.profiles ?? []).map((entry) => ({
              name: `@${entry.username}`,
              weight: entry.ratio ?? 0,
              value: entry.ratio === null ? '—' : entry.ratio.toFixed(2),
              sub: `${entry.reviews.toLocaleString()} / ${entry.films.toLocaleString()}`,
              tone:
                (entry.ratio ?? 0) >= 0.3
                  ? 'var(--ok)'
                  : (entry.ratio ?? 0) >= 0.1
                    ? 'var(--accent)'
                    : 'var(--barmuted)',
            }))}
          />
        )}
      </Panel>
    </>
  );
}
