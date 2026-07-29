'use client';

import React from 'react';
import { ArrowRight, Clock3, Heart, ListChecks, Radar, RefreshCw, Star } from 'lucide-react';
import { useRouter } from 'next/navigation';

import type { RecentChange, RecentChangesResponse } from '../../services/api';

const CHANGE_LABELS: Record<string, string> = {
  film_added: 'Film added',
  film_removed: 'Film removed',
  rating_changed: 'Rating changed',
  like_changed: 'Like changed',
  watchlist_added: 'Added to watchlist',
  watchlist_removed: 'Removed from watchlist',
  favorite_added: 'Favorite added',
  favorite_removed: 'Favorite removed',
  favorite_moved: 'Favorite reordered',
  diary_added: 'Diary entry added',
  diary_removed: 'Diary entry removed',
  review_added: 'Review added',
  review_removed: 'Review removed',
  review_updated: 'Review updated',
  list_added: 'List added',
  list_removed: 'List removed',
  list_updated: 'List updated',
  list_item_added: 'List entry added',
  list_item_removed: 'List entry removed',
  list_item_updated: 'List entry updated',
};

function changeLabel(change: RecentChange): string {
  return CHANGE_LABELS[change.change_type]
    ?? change.change_type.replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase());
}

function changeSubject(change: RecentChange): string {
  const title = change.movie?.title ?? change.list?.name;
  const entity = change.entity_type.replaceAll('_', ' ');
  if (title) return `${change.username} · ${title}`;
  return `${change.username} · ${entity}`;
}

function changeTime(change: RecentChange): string {
  if (!change.detected_at) return '';
  const parsed = new Date(change.detected_at);
  if (Number.isNaN(parsed.getTime())) return '';
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(parsed);
}

function ChangeIcon({ change }: { change: RecentChange }) {
  const entity = `${change.change_type} ${change.entity_type}`.toLowerCase();
  const Icon = entity.includes('rating') ? Star : entity.includes('like') || entity.includes('favorite') ? Heart : entity.includes('list') ? ListChecks : Radar;
  return <Icon className="h-3.5 w-3.5" />;
}

export default function RecentChangesCard({
  data,
  loading,
  error,
  onRetry,
}: {
  data?: RecentChangesResponse;
  loading: boolean;
  error: boolean;
  onRetry: () => void;
}) {
  const router = useRouter();
  const changes = data?.changes ?? [];

  return (
    <div className="mt-5 border-t border-white/10 pt-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex shrink-0 items-center gap-3">
          <span className="grid h-9 w-9 place-items-center rounded-lg border border-cinema-400/25 bg-cinema-500/[0.08] text-cinema-300">
            <Clock3 className="h-4 w-4" />
          </span>
          <div>
            <h3 className="text-sm font-semibold text-white">New Since Last Sync</h3>
            <p className="mt-0.5 text-[11px] text-white/40">Observed database changes, not inferred viewing activity.</p>
          </div>
        </div>

        {loading ? (
          <p className="text-xs text-white/40">Checking the latest sync…</p>
        ) : error ? (
          <button type="button" onClick={onRetry} className="flex items-center gap-2 text-xs font-semibold text-white/50 hover:text-white">
            <RefreshCw className="h-3.5 w-3.5" /> Change history unavailable · retry
          </button>
        ) : changes.length === 0 ? (
          <p className="text-xs text-white/45">No recorded changes after the previous successful sync.</p>
        ) : (
          <div className="flex min-w-0 flex-1 gap-2 overflow-x-auto lg:justify-end">
            {changes.slice(0, 3).map((change) => (
              <span key={change.id} className="flex min-w-44 max-w-64 shrink-0 items-center gap-2 rounded-lg border border-white/[0.08] bg-black/15 px-3 py-2 text-xs text-white/55">
                <span className="text-cinema-400"><ChangeIcon change={change} /></span>
                <span className="min-w-0">
                  <span className="block truncate font-semibold text-white/70">{changeLabel(change)}</span>
                  <span className="mt-0.5 block truncate text-[10px] text-white/40">
                    {changeSubject(change)}{changeTime(change) ? ` · ${changeTime(change)}` : ''}
                  </span>
                </span>
              </span>
            ))}
          </div>
        )}

        <button type="button" onClick={() => router.push('/spy-signals')} className="btn-ghost flex shrink-0 items-center justify-center gap-2 border-white/10 px-3 py-2 text-xs">
          Investigate <ArrowRight className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
