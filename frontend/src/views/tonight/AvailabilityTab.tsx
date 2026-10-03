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
        src="cached provider offers × watchlist_items"
        blurb={`Queued films with recorded subscription offers ${region === 'ALL' ? 'in at least one supported country — choose your country for local results' : `in ${region}`}. Offers can change after the recorded check.`}
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
                  title: region === 'ALL' ? 'No country offers have been read' : `${region} has never been read`,
                  body: 'No provider reading exists for this region, so this is empty for want of a fetch rather than for want of availability. The panel below names the regions we do hold.',
                }
              : {
                  title: 'No recorded subscription offers for this selection',
                  body: 'This may reflect incomplete coverage or older provider data. It is not proof that the films are unavailable; try a different country and verify directly with the provider.',
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
              dim: !film.checked_at || (film.stale ?? regionIsStale),
            }))}
          />
        )}
      </Panel>

      <Panel
        title="HOW FRESH THIS IS"
        src="provider-specific read dates"
        blurb="Availability is the fastest-rotting data in the product. Anything not re-read within fourteen days is labelled stale rather than shown as fact."
        caveat="Readings cover this group's queued films. The oldest contributing read sets the date; a fresh film cannot hide stale offers elsewhere. A country we have not read is not proof of no availability."
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
                  entry.unknown
                    ? 'Some read dates unknown — verify offers'
                    : entry.stale
                    ? 'Stale — shown greyed, not hidden'
                    : entry.region === region
                      ? 'Fresh — everything on this tab'
                      : 'Fresh enough',
                  {
                    font: 's',
                    size: '10px',
                    tone: entry.stale || entry.unknown ? 'var(--accent)' : 'var(--ok)',
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
        blurb="Provider data tells us where a film was offered, not when it will leave."
      >
        {/* Stated rather than quietly omitted. A reader who expected a
            "leaving soon" list is owed the reason it is not here. */}
        <div className="px-[10px] py-[14px]">
          <h3 className="m-0 font-term-sans text-t115 font-semibold text-term-ink">
            Check the offer before movie night
          </h3>
          <p className="m-0 mt-[5px] max-w-[42rem] font-term-sans text-t105 text-term-ink3">
            Choose your country for local results. Worldwide means an offer exists somewhere,
            not necessarily where you live. This page lists subscription offers; rentals and
            purchases are separate options in Tonight&rsquo;s shortlist. Check the provider
            before watching, especially when the read date is old or unknown. We do not invent
            leaving dates when the source does not publish them.
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
