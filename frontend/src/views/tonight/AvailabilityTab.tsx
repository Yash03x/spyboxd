'use client';

import React from 'react';
import { useQuery } from '@tanstack/react-query';

import Panel from '../../components/terminal/Panel';
import Posters from '../../components/terminal/bodies/Posters';
import Rows, { cell } from '../../components/terminal/bodies/Rows';
import { panelState } from '../../components/terminal/states';
import { sectionHref } from '../../components/terminal/sections';
import { tonightApi } from '../../services/api';

export default function AvailabilityTab({
  profiles,
  region,
}: {
  profiles: string[];
  region: string;
}) {
  const availabilityQuery = useQuery({
    queryKey: ['tonight-availability', profiles, region],
    queryFn: () => tonightApi.getAvailability(profiles, region),
    enabled: profiles.length > 0,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  // The selected region's staleness, as the freshness panel below reports it.
  const regionIsStale = Boolean(
    availabilityQuery.data?.regions.find((entry) => entry.region === region)?.stale,
  );

  return (
    <>
      <Panel
        title="WHERE A QUEUED FILM CAN BE WATCHED"
        src="movie_watch_providers × watchlist_items"
        blurb={`Films somebody in the selection has queued that a subscription service carries in ${region} right now.`}
        caveat={
          availabilityQuery.data
            ? `${availabilityQuery.data.caveat}${
                availabilityQuery.data.films.length > 10
                  ? ` The ten most wanted are shown of ${availabilityQuery.data.films.length}.`
                  : ''
              }`
            : undefined
        }
      >
        {panelState({
          isLoading: availabilityQuery.isLoading,
          error: availabilityQuery.error,
          isEmpty: (availabilityQuery.data?.films.length ?? 0) === 0,
          onRetry: () => availabilityQuery.refetch(),
          errorTitle: 'Availability could not be read',
          errorBody: 'Every other panel on this tab is unaffected.',
          // "Nothing is carried here" and "we have never looked here" are
          // opposite facts, and the panel below already refuses to conflate
          // them. Availability said the first while meaning the second.
          empty:
            availabilityQuery.data && !availabilityQuery.data.region_read
              ? {
                  title: `${region} has never been read`,
                  body: 'No provider reading exists for this region, so this is empty for want of a fetch rather than for want of availability. The panel below names the regions we do hold.',
                }
              : {
                  title: `Nothing queued is carried in ${region}`,
                  body: 'That is a fact about this region at the last reading, not about the films. Another region may carry them.',
                },
        }) ?? (
          <Posters
            items={(availabilityQuery.data?.films ?? []).slice(0, 10).map((film) => ({
              title: film.year ? `${film.title} (${film.year})` : film.title,
              posterUrl: film.poster_url,
              href: film.letterboxd_url ?? undefined,
              sub: `${film.providers.join(', ')} · queued by ${film.usernames.map((name) => `@${name}`).join(', ')}`,
              right: `${film.wanted_by} want it`,
              tone: film.wanted_by > 1 ? 'var(--ok)' : 'var(--accent)',
              rightCaption: film.checked_at
                ? `read ${new Date(film.checked_at).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })}`
                : 'read date unknown',
              // The freshness table one card down says a stale reading is
              // "shown greyed, not hidden"; nothing was ever greyed. The
              // verdict comes from that same table's own row for this region
              // rather than from a clock read during render -- the server has
              // already decided, and it decides for every film here at once.
              dim: regionIsStale,
            }))}
          />
        )}
      </Panel>

      <Panel
        title="HOW FRESH THIS IS"
        src="movie_watch_providers.fetched_at"
        blurb="Availability is the fastest-rotting data in the product. Anything not re-read within fourteen days is labelled stale rather than shown as fact."
        caveat="Provider readings are per region, so a region we have never fetched has no rows rather than no availability."
      >
        {panelState({
          isLoading: availabilityQuery.isLoading,
          error: availabilityQuery.error,
          isEmpty: (availabilityQuery.data?.regions.length ?? 0) === 0,
          onRetry: () => availabilityQuery.refetch(),
          errorTitle: 'Region freshness could not be read',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No provider data imported',
            body: 'Nothing has been fetched from the provider feed yet, for any region.',
          },
        }) ?? (
          <Rows
            columns="76px 76px 86px minmax(0,1fr)"
            head={['REGION', ['FILMS', 'right'], ['CHECKED', 'right'], 'STATE']}
            rows={(availabilityQuery.data?.regions ?? []).map((entry) => ({
              cells: [
                cell(entry.region),
                cell(entry.films.toLocaleString(), { align: 'right', tone: 'var(--ink)' }),
                cell(entry.days_ago === null ? '—' : entry.days_ago === 0 ? 'today' : `${entry.days_ago}d ago`, {
                  align: 'right',
                  size: '10px',
                  tone: 'var(--muted)',
                }),
                cell(
                  entry.stale
                    ? 'Stale — shown greyed, not hidden'
                    : entry.region === region
                      ? 'Fresh — everything on this tab'
                      : 'Fresh enough',
                  {
                    font: 's',
                    size: '10px',
                    tone: entry.stale ? 'var(--accent)' : 'var(--ok)',
                    wrap: true,
                  },
                ),
              ],
            }))}
          />
        )}
      </Panel>

      <Panel
        title="WHY THERE IS NO COUNTDOWN"
        src="the data ceiling"
        blurb="The one panel this section was designed around, and the one the schema cannot support."
      >
        {/* Stated rather than quietly omitted. A reader who expected a
            "leaving soon" list is owed the reason it is not here. */}
        <div className="px-[10px] py-[14px]">
          <h3 className="m-0 font-term-sans text-t115 font-semibold text-term-ink">
            Can&rsquo;t answer this yet
          </h3>
          <p className="m-0 mt-[5px] max-w-[42rem] font-term-sans text-t105 text-term-ink3">
            A countdown needs an expiry date. The provider feed publishes which services carry a
            film today and nothing about when that stops being true, so every &ldquo;4 days
            left&rdquo; would be a guess wearing a number&rsquo;s clothes. Two consecutive readings
            of the same region would let us report a departure <em>after</em> it happened, which is
            a weaker but honest claim; until that history exists, availability is shown with its
            read date attached and no deadline claimed.
          </p>
          <p className="m-0 mt-[8px] max-w-[42rem] font-term-sans text-t10 text-term-dim">
            The refresh ledger in{' '}
            <a href={sectionHref('data', 'refreshes')}>Data › Refreshes</a> shows when each region
            was last read, which is the input that history would be built from.
          </p>
        </div>
      </Panel>
    </>
  );
}
