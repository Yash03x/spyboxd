'use client';

import { SignOutButton, UserButton, useAuth } from '@clerk/nextjs';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import type { ReactNode } from 'react';

import Panel from '../components/terminal/Panel';
import Bars from '../components/terminal/bodies/Bars';
import Notes from '../components/terminal/bodies/Notes';
import Rows, { cell } from '../components/terminal/bodies/Rows';
import Spark from '../components/terminal/bodies/Spark';
import { BarsSkeleton, PanelError, PanelSkeleton } from '../components/terminal/states';
import { ThemeToggle } from '../components/terminal/theme';
import { publicDashboardApi } from '../services/api';

const RATING_ORDER = ['5.0', '4.5', '4.0', '3.5', '3.0', '2.5', '2.0', '1.5', '1.0', '0.5'];

const STAR_LABEL: Record<string, string> = {
  '5.0': '★★★★★', '4.5': '★★★★½', '4.0': '★★★★', '3.5': '★★★½', '3.0': '★★★',
  '2.5': '★★½', '2.0': '★★', '1.5': '★½', '1.0': '★', '0.5': '½',
};

const MONTH_INITIAL = ['J', 'F', 'M', 'A', 'M', 'J', 'J', 'A', 'S', 'O', 'N', 'D'];

/**
 * The signed-out landing page. Deliberately outside the six sections — no rail,
 * no tab row — but the same panels, tokens and voice, because a visitor's first
 * impression of the product should be the product.
 *
 * Nothing here identifies anybody. Every figure is a database-wide total or an
 * anonymous distribution; names, pairs, titles and dates stay inside the
 * signed-in workspace.
 */
export default function PublicDashboard() {
  const { isSignedIn } = useAuth();
  const dashboardQuery = useQuery({
    queryKey: ['public-dashboard-analytics'],
    queryFn: publicDashboardApi.getAnalytics,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const renderShell = (content: ReactNode) => (
    <main className="terminal-root min-h-screen" data-testid="public-dashboard">
      <PublicHeader isSignedIn={isSignedIn} />
      <div className="px-[14px] pt-[14px]">
        <div className="flex flex-wrap items-baseline gap-[10px]">
          <h1 className="m-0 max-w-4xl font-term-sans text-t20 font-bold tracking-head text-term-ink">
            Movie activity at a glance, without exposing anyone&apos;s profile.
          </h1>
        </div>
        <p className="m-0 mt-[6px] max-w-[54rem] font-term-sans text-t115 text-term-ink3">
          These are database-wide totals and anonymous distributions. Sign in to choose the profiles
          you monitor, compare people, and investigate same-day watches.
        </p>
      </div>
      <div
        className="grid items-start gap-3 p-[14px]"
        style={{ gridTemplateColumns: 'repeat(auto-fit,minmax(min(400px,100%),1fr))' }}
      >
        {content}
      </div>
    </main>
  );

  if (dashboardQuery.isLoading) {
    return renderShell(
      <>
        <Panel title="THE WHOLE DATABASE, IN FOUR NUMBERS" src="rollups">
          <PanelSkeleton rows={2} height={21} />
        </Panel>
        <Panel title="HOW EVERYBODY RATES" src="ratings.rating">
          <BarsSkeleton rows={10} />
        </Panel>
      </>,
    );
  }

  if (dashboardQuery.error || !dashboardQuery.data) {
    return renderShell(
      <Panel title="PUBLIC TOTALS" src="rollups" wide>
        <PanelError
          severity="fatal"
          title="The public dashboard could not be loaded."
          body="The aggregate endpoint did not respond. Nothing on this page can be shown without it."
          onRetry={() => dashboardQuery.refetch()}
          actionLabel="RELOAD"
        />
      </Panel>,
    );
  }

  const analytics = dashboardQuery.data;
  const stats = analytics.system_stats;
  const signals = analytics.signal_counts;
  const lastSync = analytics.data_health.last_synced_at
    ? new Date(analytics.data_health.last_synced_at).toLocaleDateString('en-GB', {
        day: '2-digit', month: 'short', year: 'numeric',
      })
    : 'Not yet';

  const distribution = analytics.rating_distribution ?? {};
  const ratingTotal = Object.values(distribution).reduce((sum, value) => sum + value, 0);
  const ratingBars = RATING_ORDER.filter((key) => key in distribution).map((key) => ({
    name: STAR_LABEL[key] ?? key,
    weight: distribution[key],
    value: distribution[key].toLocaleString(),
    sub: ratingTotal ? `${Math.round((distribution[key] / ratingTotal) * 100)}%` : '',
  }));

  // A month still in progress is not a month with less watching in it. The
  // average is taken over completed months only, and the partial one is named
  // rather than quietly dragging the figure down.
  const activity = analytics.activity_data ?? [];
  const completedMonths = activity.filter((entry) => !entry.is_partial);
  const partialMonth = activity.find((entry) => entry.is_partial);
  const completed = {
    months: completedMonths.length,
    watchAverage: completedMonths.length
      ? completedMonths.reduce((sum, entry) => sum + entry.movies_watched, 0) / completedMonths.length
      : 0,
    uniqueAverage: completedMonths.length
      ? completedMonths.reduce((sum, entry) => sum + (entry.unique_movies ?? 0), 0) /
        completedMonths.length
      : 0,
  };
  const partialLabel = partialMonth
    ? new Date(`${partialMonth.month}-01T00:00:00Z`).toLocaleDateString('en-GB', {
        month: 'long',
        year: 'numeric',
        timeZone: 'UTC',
      })
    : null;
  const activityCaveat = partialLabel
    ? `${partialLabel} is month to date and is excluded from the completed-month average, which is taken over ${completed.months} completed month${completed.months === 1 ? '' : 's'}.`
    : `Averaged over ${completed.months} completed month${completed.months === 1 ? '' : 's'}.`;

  const sparkItems = activity.map((entry) => {
    const month = Number(entry.month?.slice(5, 7) ?? '1') - 1;
    return {
      label: MONTH_INITIAL[Number.isNaN(month) ? 0 : month] ?? '?',
      value: entry.movies_watched,
      inner: entry.unique_movies ?? undefined,
      display: entry.movies_watched === 0 ? '—' : String(entry.movies_watched),
      partial: entry.is_partial,
      hint: `${new Date(`${entry.month}-01T00:00:00Z`).toLocaleDateString('en-GB', { month: 'long', year: 'numeric', timeZone: 'UTC' })}${entry.is_partial ? ', month to date' : ''}: ${entry.movies_watched} watch events; ${entry.unique_movies ?? 0} unique films${entry.average_rating === null ? '' : `; average rating ${entry.average_rating}`}`,
    };
  });

  return renderShell(
    <>
      <Panel
        title="THE WHOLE DATABASE, IN FOUR NUMBERS"
        src="rollups · profiles · movies"
        stats={[
          { big: stats.total_profiles.toLocaleString(), unit: 'PROFILES', tone: 'var(--accent)' },
          { big: stats.total_movies_tracked.toLocaleString(), unit: 'UNIQUE FILMS' },
          { big: stats.total_reviews.toLocaleString(), unit: 'REVIEWS' },
          { big: stats.global_avg_rating.toFixed(2), unit: 'AVERAGE' },
        ]}
        // Completed over ACTIVE, not over total_profiles — the snapshot's
        // total is itself completed-only, so the old caveat compared a number
        // against itself and could only ever read "N of N ready".
        caveat={`${analytics.data_health.completed_profiles} of ${analytics.data_health.active_profiles} monitored profiles are ready for analysis. Latest completed sync: ${lastSync}.`}
      />

      <Panel
        title="HOW EVERYBODY RATES"
        src="ratings.rating"
        blurb="The whole distribution, not an average. Anonymous — a bar is a count of ratings, never a person."
      >
        <Bars items={ratingBars} />
      </Panel>

      <Panel
        title="ACTIVITY, MONTH BY MONTH"
        src="watch_events.watched_date"
        blurb="Full bar is watches. The lighter block inside it is films nobody in the database had logged before."
        stats={
          completed.months
            ? [
                { big: completed.watchAverage.toFixed(1), unit: 'WATCHES / MONTH' },
                { big: completed.uniqueAverage.toFixed(1), unit: 'UNIQUE FILMS / MONTH' },
              ]
            : undefined
        }
        caveat={activityCaveat}
      >
        <Spark items={sparkItems} />
      </Panel>

      <Panel
        title="ANONYMOUS OVERLAP TOTALS"
        src="watch_events × watch_events"
        blurb="How much overlap exists in the dataset. Names, profile pairs, titles, ratings and watch dates stay inside the signed-in workspace."
        wide
      >
        <Rows
          columns="minmax(0,1fr) 90px"
          head={['WHAT', ['COUNT', 'right']]}
          rows={[
            ['Same-day watches', signals.same_day_events],
            ['Within a day', signals.one_day_gap_events],
            ['Shared titles', signals.shared_titles],
            ['Profiles carrying diary dates', signals.profiles_with_diary_dates],
          ].map(([label, value]) => ({
            cells: [
              cell(label as string, { font: 's', size: '11px' }),
              cell((value as number).toLocaleString(), { align: 'right', tone: 'var(--ink)' }),
            ],
          }))}
        />
      </Panel>

      <Panel title="WHAT SIGNING IN ADDS" src="the private workspace" wide>
        <Notes
          items={[
            {
              label: 'Who watched the same thing, and when',
              text: 'Same film, close in time, named on both sides — with the honest account of how sure we are about each one.',
            },
            {
              label: 'What one person is like, and how two relate',
              text: 'Rewatches, drift, obscurity, review habits, the follow graph, and where two people part company.',
            },
            {
              label: 'What to actually watch tonight',
              text: 'Ranked across whoever is in the room, from what they have queued and what nobody has seen.',
            },
            {
              label: 'Where the data came from, and what is missing',
              text: 'Every panel names the table it reads and says what it is waiting for. Nothing here is a claim without a source.',
            },
          ]}
        />
        <div className="flex flex-wrap items-center gap-3 border-t border-term-rule2 px-[10px] py-[9px]">
          <Link
            href={isSignedIn ? '/overview' : '/sign-in?redirect_url=%2Fprofiles'}
            className="rounded-[3px] border border-term-accent bg-term-accent px-3 py-[5px] text-t105 font-bold text-term-onaccent no-underline hover:no-underline"
          >
            {isSignedIn ? 'Choose monitored profiles' : 'Sign in for private tools'}
          </Link>
          <span className="font-term-sans text-t10 text-term-dim">
            Latest completed profile sync: {lastSync}
          </span>
        </div>
      </Panel>
    </>,
  );
}

function PublicHeader({ isSignedIn }: { isSignedIn: boolean | undefined }) {
  return (
    <header className="sticky top-0 z-50 flex h-[34px] items-center justify-between gap-4 border-b border-term-rule bg-term-bg2 px-3 text-t105">
      <Link href="/" className="flex shrink-0 items-center gap-[10px] no-underline hover:no-underline" aria-label="Spyboxd public dashboard">
        <span className="grid h-[22px] w-[22px] place-items-center rounded-[3px] bg-term-accent text-[11px] font-extrabold text-term-onaccent">
          S
        </span>
        <span className="font-bold tracking-crumb text-term-accent">SPYBOXD</span>
        <span className="hidden text-term-dim2 sm:inline">›</span>
        <span className="hidden text-term-ink3 sm:inline">PUBLIC TOTALS</span>
      </Link>
      <div className="flex min-w-0 shrink-0 items-center gap-2 overflow-x-auto text-term-muted">
        {isSignedIn ? (
          <>
            <Link
              href="/overview"
              className="rounded-[3px] border border-term-accent px-2 py-[3px] text-term-accent no-underline hover:no-underline"
            >
              Open My Dashboard
            </Link>
            <SignOutButton redirectUrl="/">
              <button
                type="button"
                className="rounded-[3px] border border-term-rule px-2 py-[3px] hover:border-term-accent hover:text-term-accent"
              >
                Sign out
              </button>
            </SignOutButton>
            <UserButton />
          </>
        ) : (
          <>
            <Link
              href="/sign-up"
              className="rounded-[3px] border border-term-accent bg-term-accent px-2 py-[3px] font-bold text-term-onaccent no-underline hover:no-underline"
            >
              Create account
            </Link>
            <Link
              href="/sign-in?redirect_url=%2Fprofiles"
              className="rounded-[3px] border border-term-rule px-2 py-[3px] text-term-ink3 no-underline hover:border-term-accent hover:text-term-accent hover:no-underline"
            >
              Sign in to monitor profiles
            </Link>
          </>
        )}
        <ThemeToggle />
      </div>
    </header>
  );
}
