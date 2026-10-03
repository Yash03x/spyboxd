'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useState } from 'react';

export const INSIGHT_DESTINATIONS = [
  { section: 'anime', tab: 'overview', title: 'Explore my anime insights', description: 'A private MAL export workspace for scores, episode progress, timelines and searchable title evidence.', keywords: 'anime myanimelist mal personal export manga' },
  { section: 'films', tab: 'research', title: 'Research periods and compare groups', description: 'Custom date ranges, period changes, exact watch evidence, sortable results and CSV exports.', keywords: 'deep dive statistical research trends group comparison export download csv period dates' },
  { section: 'people', tab: 'one', title: 'Explore one person', description: 'Watching history, rating habits, favourite genres, directors and activity.', keywords: 'individual profile stats statistics streak runtime' },
  { section: 'overlaps', tab: 'together', title: 'Find shared watches', description: 'Which people logged the same films close in time, with evidence and confidence.', keywords: 'group spy spying same day overlap together' },
  { section: 'overlaps', tab: 'echoes', title: 'Discover patterns between people', description: 'Rewatches, recurring sequences and related films across your selected group.', keywords: 'trends influence patterns echoes' },
  { section: 'overlaps', tab: 'when', title: 'See when the group watches', description: 'Calendar patterns and the timing of shared activity.', keywords: 'timeline time dates weekly monthly calendar' },
  { section: 'people', tab: 'two', title: 'Compare two people', description: 'Shared films, rating differences and taste alignment.', keywords: 'pair comparison match similarity ratings' },
  { section: 'films', tab: 'trends', title: 'Explore group trends and taste', description: 'Yearly activity, individual contributions, genres, languages and countries across a chosen group.', keywords: 'group trends stats statistics taste map genre directors language country decades' },
  { section: 'films', tab: 'library', title: 'Explore the film library', description: 'Recurring subjects, runtimes, countries, filmography runs and collections.', keywords: 'movies film library runtime keyword' },
  { section: 'tonight', tab: 'picks', title: 'Find a film for your group', description: 'A shared shortlist with runtime, genre, streaming and rewatch preferences.', keywords: 'recommendations tonight group pick best movie watchlist' },
  { section: 'tonight', tab: 'lists', title: 'Explore lists and unfinished films', description: 'List progress and films your group still has to discover.', keywords: 'list completion progress mission' },
  { section: 'tonight', tab: 'leaving', title: 'Check streaming availability', description: 'Recorded subscription offers and when they were last checked.', keywords: 'where watch provider stream rent availability' },
  { section: 'people', tab: 'circle', title: 'Explore profile connections', description: 'Following relationships and the surrounding public-profile network.', keywords: 'friends follows followers network graph' },
  { section: 'people', tab: 'reach', title: 'Explore reviews and reactions', description: 'Reviews, likes and engagement recorded for a person.', keywords: 'review comments likes popular reach' },
  { section: 'overlaps', tab: 'sure', title: 'Check how strong a pattern is', description: 'Confidence, date coverage and limits behind apparent connections.', keywords: 'confidence evidence statistical bias sample certainty' },
  { section: 'data', tab: 'profiles', title: 'Choose profiles to monitor', description: 'Manage your monitored profiles or request a new public profile.', keywords: 'add track tracking monitor people onboarding' },
  { section: 'data', tab: 'refreshes', title: 'Check data freshness', description: 'Full-sync coverage, recent feed health and incomplete sources.', keywords: 'refresh stale update rss full sync data freshness' },
  { section: 'data', tab: 'missing', title: 'Understand missing data', description: 'What was not captured and which insights that affects.', keywords: 'coverage missing gaps empty unavailable' },
];

export default function ExploreGuide() {
  const [query, setQuery] = useState('');
  const params = useSearchParams();
  const words = query.toLowerCase().trim().split(/\s+/).filter(Boolean);
  const matches = INSIGHT_DESTINATIONS.filter((item) => words.every((word) => `${item.title} ${item.description} ${item.keywords}`.toLowerCase().includes(word)));
  return (
    <details className="mt-3 border-y border-term-rule py-2 font-term-sans">
      <summary className="cursor-pointer py-1 text-t115 font-semibold text-term-accent">Find a stat, profile or group trend</summary>
      <div className="py-3">
        <label className="block text-t11 text-term-ink3" htmlFor="insight-search">What would you like to explore?</label>
        <input id="insight-search" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Try genres, shared watches, ratings or freshness" className="mt-2 w-full max-w-[36rem] rounded-[3px] border border-term-rule bg-term-bg px-3 py-2 text-t115 text-term-ink" />
        <p className="my-2 text-t105 text-term-muted" role="status">{matches.length} destinations · choose a person or group on the destination screen.</p>
        <nav aria-label="Insight guide" className="grid gap-x-6 gap-y-3 sm:grid-cols-2 xl:grid-cols-3">
          {matches.map((item) => {
            const next = new URLSearchParams(params.toString());
            next.set('tab', item.tab);
            next.delete('pick');
            return <Link key={`${item.section}/${item.tab}`} href={`/${item.section}?${next}`} className="block text-t115 text-term-accent">
              <span className="font-semibold">{item.title}</span>
              <span className="mt-1 block text-t105 font-normal text-term-ink3">{item.description}</span>
            </Link>;
          })}
        </nav>
        {!matches.length ? <p className="text-t11 text-term-muted">No matching destination. Try “group”, “ratings”, “calendar” or “profiles”.</p> : null}
      </div>
    </details>
  );
}
