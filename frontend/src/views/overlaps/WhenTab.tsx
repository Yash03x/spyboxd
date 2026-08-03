'use client';

import React from 'react';
import { useQuery } from '@tanstack/react-query';

import Panel from '../../components/terminal/Panel';
import Bars from '../../components/terminal/bodies/Bars';
import Rows, { cell } from '../../components/terminal/bodies/Rows';
import Spark from '../../components/terminal/bodies/Spark';
import { CalendarHeat } from '../../components/terminal/bodies/Matrix';
import { BarsSkeleton, panelState } from '../../components/terminal/states';
import { sectionHref } from '../../components/terminal/sections';
import { activityApi, insightsApi } from '../../services/api';

const WEEKS_SHOWN = 8;

/**
 * Fold dated buckets onto an eight-week, Monday-first grid.
 *
 * Anchored on the window the backend chose, never on today: the calendar
 * endpoint deliberately ends on the pair's own latest event, and a grid that
 * ends today would render eight weeks of empty cells for a pair whose newest
 * activity is older than that.
 */
function toWeeks(buckets: Array<{ date: string; signal_count: number }>, anchor?: string) {
  const counts = new Map(buckets.map((bucket) => [bucket.date, bucket.signal_count]));
  const latestBucket = buckets.length ? buckets[buckets.length - 1].date : undefined;
  const end = new Date(anchor ?? latestBucket ?? new Date().toISOString().slice(0, 10));
  if (Number.isNaN(end.getTime())) end.setTime(Date.now());
  // Walk forward to the Sunday of that week so the last row is complete.
  const daysPastMonday = (end.getDay() + 6) % 7;
  end.setDate(end.getDate() + (6 - daysPastMonday));

  const weeks: number[][] = [];
  const titles: string[][] = [];
  for (let week = WEEKS_SHOWN - 1; week >= 0; week -= 1) {
    const row: number[] = [];
    const rowTitles: string[] = [];
    for (let day = 0; day < 7; day += 1) {
      const cursor = new Date(end);
      cursor.setDate(end.getDate() - week * 7 - (6 - day));
      const key = cursor.toISOString().slice(0, 10);
      row.push(counts.get(key) ?? 0);
      rowTitles.push(`${key} · ${counts.get(key) ?? 0} overlaps`);
    }
    weeks.push(row);
    titles.push(rowTitles);
  }
  return { weeks, titles };
}

export default function WhenTab({ profiles, gapDays }: { profiles: string[]; gapDays: number }) {
  const calendarQuery = useQuery({
    queryKey: ['signal-calendar', profiles, gapDays],
    queryFn: () => insightsApi.getSignalCalendar(profiles, { gapDays }),
    enabled: profiles.length >= 2,
    staleTime: 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const weekdayQuery = useQuery({
    queryKey: ['activity-weekday', profiles],
    queryFn: () => activityApi.getWeekdayRhythm(profiles),
    enabled: profiles.length > 0,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const seasonQuery = useQuery({
    queryKey: ['activity-season', profiles],
    queryFn: () => activityApi.getSeasonShape(profiles),
    enabled: profiles.length > 0,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const marathonsQuery = useQuery({
    queryKey: ['activity-marathons', profiles, 'when'],
    queryFn: () => activityApi.getMarathons(profiles, 10),
    enabled: profiles.length > 0,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const grid = toWeeks(calendarQuery.data?.buckets ?? [], calendarQuery.data?.to);
  const hasOverlapDays = grid.weeks.some((week) => week.some((value) => value > 0));
  const season = seasonQuery.data;

  return (
    <>
      <Panel
        title="WHEN YOU OVERLAP"
        src="watch_events.watched_date"
        wide
        blurb="Eight weeks, one square per day, darker where more overlaps landed."
        caveat={
          calendarQuery.data
            ? `Eight weeks ending ${new Date(calendarQuery.data.to).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })} — this pair's most recent overlap, not today. Undated diary entries cannot be placed on a grid at all, so a quiet week can mean a quiet week or a profile with no dates.`
            : 'Undated diary entries cannot be placed on a grid at all, so a quiet week here can mean a quiet week or a profile with no dates.'
        }
      >
        {panelState({
          isLoading: calendarQuery.isLoading,
          error: calendarQuery.error,
          isEmpty: profiles.length < 2 || !hasOverlapDays,
          onRetry: () => calendarQuery.refetch(),
          errorTitle: 'The overlap calendar could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No dated overlaps in the last eight weeks',
            body: 'Dated watch events on both sides are required to place a day on the grid. Widen the closeness above, or check what each profile is missing.',
            cta: { label: 'SEE WHAT EACH VIEW NEEDS', href: sectionHref('data', 'missing') },
          },
        }) ?? <CalendarHeat weeks={grid.weeks} titles={grid.titles} />}
      </Panel>

      <Panel
        title="WEEKDAY RHYTHM"
        src="watch_events weekday"
        blurb="Diary entries carry a date but no clock, so this is as fine-grained as time gets. There is no late-night pattern to find."
        caveat={weekdayQuery.data?.caveat}
      >
        {panelState({
          isLoading: weekdayQuery.isLoading,
          error: weekdayQuery.error,
          isEmpty: (weekdayQuery.data?.total ?? 0) === 0,
          onRetry: () => weekdayQuery.refetch(),
          errorTitle: 'Weekday rhythm could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No dated watches',
            body: 'Every entry in this selection is undated, so no day of the week can be assigned.',
          },
          skeleton: <BarsSkeleton rows={7} />,
        }) ?? (
          <Bars
            items={(weekdayQuery.data?.days ?? []).map((day) => ({
              name: day.label,
              weight: day.watches,
              value: day.watches.toLocaleString(),
              sub: day.share === null ? '' : `${Math.round(day.share * 100)}%`,
            }))}
          />
        )}
      </Panel>

      <Panel
        title="SEASON SHAPE"
        isNew
        src="watch_events month-of-year"
        blurb="Month of year across every year at once. A single year cannot separate a seasonal habit from a busy month; stacking them can."
        caveat={season?.caveat}
      >
        {panelState({
          isLoading: seasonQuery.isLoading,
          error: seasonQuery.error,
          isEmpty: (season?.total ?? 0) === 0,
          onRetry: () => seasonQuery.refetch(),
          errorTitle: 'Season shape could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No dated watches to fold',
            body: 'Folding years onto twelve months needs dated entries. This selection has none.',
          },
        }) ?? (
          <Spark
            items={(season?.months ?? []).map((month) => ({
              label: month.label,
              value: month.watches,
              display:
                month.watches === 0
                  ? '—'
                  : month.watches >= 1000
                    ? `${(month.watches / 1000).toFixed(1)}k`
                    : String(month.watches),
            }))}
          />
        )}
      </Panel>

      <Panel
        title="LONGEST MARATHON DAYS"
        src="watch_events grouped by date"
        blurb="Three or more films logged by one person in a day, ordered by how many."
        caveat={marathonsQuery.data?.caveat}
      >
        {panelState({
          isLoading: marathonsQuery.isLoading,
          error: marathonsQuery.error,
          isEmpty: (marathonsQuery.data?.marathons.length ?? 0) === 0,
          onRetry: () => marathonsQuery.refetch(),
          errorTitle: 'Marathon days could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No marathon days yet',
            body: 'Nobody in the selection has three or more dated films on one day.',
          },
        }) ?? (
          <Rows
            columns="68px minmax(0,1fr) 30px"
            head={['DATE', 'WHO · WHAT', ['N', 'right']]}
            rows={[...(marathonsQuery.data?.marathons ?? [])]
              .sort((a, b) => b.films - a.films)
              .slice(0, 8)
              .map((day) => ({
                cells: [
                  cell(
                    new Date(day.date).toLocaleDateString('en-GB', {
                      day: '2-digit',
                      month: 'short',
                    }),
                    { size: '10.5px', tone: 'var(--ink3)' },
                  ),
                  cell(`@${day.username} · ${day.titles.slice(0, 3).join(', ')}`, {
                    font: 's',
                    size: '10.5px',
                    wrap: true,
                  }),
                  cell(String(day.films), { align: 'right', tone: 'var(--accent)' }),
                ],
              }))}
          />
        )}
      </Panel>
    </>
  );
}
