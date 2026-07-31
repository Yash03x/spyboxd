'use client';

import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { Tags } from 'lucide-react';

import type { TagCount } from '../../services/api';

const COLLAPSED_TAG_LIMIT = 24;

export function TagChipList({ tags, className = '' }: { tags?: string[]; className?: string }) {
  if (!tags || tags.length === 0) {
    return null;
  }
  return (
    <div className={`flex flex-wrap gap-1.5 ${className}`}>
      {tags.map((tag) => (
        <span
          key={tag}
          className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] font-medium text-white/45"
        >
          {tag}
        </span>
      ))}
    </div>
  );
}

export default function TagsPanel({
  tagCounts,
  username,
  delay = 0,
}: {
  tagCounts?: TagCount[];
  username: string;
  delay?: number;
}) {
  const [expanded, setExpanded] = useState(false);

  const sortedTags = [...(tagCounts ?? [])].sort(
    (a, b) => b.count - a.count || a.tag.localeCompare(b.tag),
  );
  const visibleTags = expanded ? sortedTags : sortedTags.slice(0, COLLAPSED_TAG_LIMIT);

  return (
    <motion.div
      className="analysis-panel"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay }}
    >
      <h2 className="flex items-center gap-2 text-xl font-semibold text-white">
        <Tags className="h-5 w-5 text-cinema-400" aria-hidden="true" /> Tags
      </h2>
      <p className="mt-1 text-sm text-white/60">
        Letterboxd tags @{username} has applied across synced films, sorted by usage.
      </p>

      {sortedTags.length > 0 ? (
        <>
          <div className="mt-5 flex flex-wrap gap-2">
            {visibleTags.map((entry) => (
              <span
                key={entry.tag}
                className="inline-flex items-center gap-1.5 rounded-full border border-cinema-400/20 bg-cinema-500/10 px-3 py-1 text-xs font-medium text-cinema-300"
              >
                {entry.tag}
                <span className="text-[10px] font-semibold text-white/40">{entry.count}</span>
              </span>
            ))}
          </div>
          {sortedTags.length > COLLAPSED_TAG_LIMIT && (
            <button
              type="button"
              onClick={() => setExpanded((value) => !value)}
              className="btn-ghost mt-4 border-white/10 px-4 py-2 text-xs"
            >
              {expanded ? 'Show fewer tags' : `Show all ${sortedTags.length} tags`}
            </button>
          )}
        </>
      ) : (
        <p className="mt-5 text-sm text-white/50">No tags synced.</p>
      )}
    </motion.div>
  );
}
