'use client';

import React, { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Archive, Ghost, Heart, MessageSquare } from 'lucide-react';

import { memberArchiveApi } from '../../services/api';

interface ArchivePanelProps {
  username: string;
}

type ArchiveTab = 'lost' | 'likes' | 'comments';

function formatDate(value: string | null): string {
  if (!value) return '';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? ''
    : parsed.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

/**
 * Surfaces that only exist in official Letterboxd account exports: content the
 * member liked elsewhere, their own comments, and entries Letterboxd could no
 * longer place (deleted films/threads and orphaned rows).
 */
const ArchivePanel: React.FC<ArchivePanelProps> = ({ username }) => {
  const [activeTab, setActiveTab] = useState<ArchiveTab>('lost');

  const archiveQuery = useQuery({
    queryKey: ['member-archive', username],
    queryFn: () => memberArchiveApi.getArchive(username),
    enabled: Boolean(username),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  const data = archiveQuery.data;
  const totals = data?.totals;
  const hasAnything = Boolean(
    totals && (totals.lost_entries || totals.liked_reviews || totals.liked_lists || totals.comments),
  );

  const tabs = useMemo(
    () => [
      { id: 'lost' as const, label: 'Lost history', icon: Ghost, count: totals?.lost_entries ?? 0 },
      {
        id: 'likes' as const,
        label: 'Liked content',
        icon: Heart,
        count: (totals?.liked_reviews ?? 0) + (totals?.liked_lists ?? 0),
      },
      { id: 'comments' as const, label: 'Comments', icon: MessageSquare, count: totals?.comments ?? 0 },
    ],
    [totals],
  );

  if (archiveQuery.isError || (archiveQuery.isSuccess && !hasAnything)) {
    return (
      <section className="rounded-xl border border-white/10 bg-white/5 p-4">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-white/75">
          <Archive className="h-4 w-4 text-cinema-400" />
          Export archive
        </h2>
        <p className="mt-2 text-xs leading-5 text-white/40">
          No export-only data for this profile. Liked reviews and lists, comments, and lost history
          come from an official Letterboxd account export rather than public pages.
        </p>
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-white/10 bg-white/5 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-white/75">
          <Archive className="h-4 w-4 text-cinema-400" />
          Export archive
        </h2>
        <div className="flex flex-wrap gap-1">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                aria-pressed={isActive}
                className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold transition-colors ${
                  isActive ? 'bg-cinema-500/20 text-cinema-300' : 'text-white/45 hover:text-white/75'
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                {tab.label}
                <span className="text-white/35">{tab.count}</span>
              </button>
            );
          })}
        </div>
      </div>

      {archiveQuery.isLoading && <p className="text-xs text-white/40">Loading archive…</p>}

      {activeTab === 'lost' && data && (
        <ul className="space-y-1.5">
          {data.lost_entries.slice(0, 40).map((entry, index) => (
            <li
              key={`${entry.source_url ?? entry.title ?? 'lost'}-${index}`}
              className="flex items-center justify-between gap-3 rounded-lg border border-white/5 bg-black/20 px-3 py-2 text-sm"
            >
              <span className="min-w-0 truncate text-white/80">
                <span className="mr-2 rounded bg-white/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-white/45">
                  {entry.lost_kind}
                </span>
                {entry.title ?? entry.source_url}
                {entry.release_year ? <span className="text-white/35"> ({entry.release_year})</span> : null}
              </span>
              <span className="shrink-0 text-xs text-white/40">
                {entry.body_text?.startsWith('From list:') ? entry.body_text : formatDate(entry.entry_date)}
              </span>
            </li>
          ))}
          {data.lost_entries.length === 0 && (
            <li className="text-xs text-white/40">Nothing lost — every entry still resolves on Letterboxd.</li>
          )}
        </ul>
      )}

      {activeTab === 'likes' && data && (
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <h3 className="mb-2 text-xs font-semibold text-white/55">Liked reviews</h3>
            <ul className="space-y-1">
              {data.liked_reviews.slice(0, 20).map((like) => (
                <li key={like.target_url} className="flex items-center justify-between gap-2 text-xs">
                  <a
                    href={like.target_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="truncate text-cinema-300 hover:text-cinema-200 hover:underline"
                  >
                    {like.target_url.replace('https://', '')}
                  </a>
                  <span className="shrink-0 text-white/35">{formatDate(like.liked_date)}</span>
                </li>
              ))}
              {data.liked_reviews.length === 0 && <li className="text-xs text-white/40">None.</li>}
            </ul>
          </div>
          <div>
            <h3 className="mb-2 text-xs font-semibold text-white/55">Liked lists</h3>
            <ul className="space-y-1">
              {data.liked_lists.slice(0, 20).map((like) => (
                <li key={like.target_url} className="flex items-center justify-between gap-2 text-xs">
                  <a
                    href={like.target_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="truncate text-cinema-300 hover:text-cinema-200 hover:underline"
                  >
                    {like.target_url.replace('https://', '')}
                  </a>
                  <span className="shrink-0 text-white/35">{formatDate(like.liked_date)}</span>
                </li>
              ))}
              {data.liked_lists.length === 0 && <li className="text-xs text-white/40">None.</li>}
            </ul>
          </div>
        </div>
      )}

      {activeTab === 'comments' && data && (
        <ul className="space-y-2">
          {data.comments.slice(0, 20).map((comment, index) => (
            <li
              key={`${comment.target_url}-${index}`}
              className="rounded-lg border border-white/5 bg-black/20 px-3 py-2"
            >
              <div className="flex items-center justify-between gap-2 text-xs">
                <a
                  href={comment.target_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="truncate text-cinema-300 hover:text-cinema-200 hover:underline"
                >
                  {comment.target_url.replace('https://', '')}
                </a>
                <span className="shrink-0 text-white/35">{formatDate(comment.commented_date)}</span>
              </div>
              {comment.comment_text && (
                // The API parses export comment markup into plain text, so
                // this is an ordinary escaped React text child.
                <p className="mt-1 line-clamp-3 text-sm text-white/70">{comment.comment_text}</p>
              )}
            </li>
          ))}
          {data.comments.length === 0 && <li className="text-xs text-white/40">No comments in the export.</li>}
        </ul>
      )}
    </section>
  );
};

export default ArchivePanel;
