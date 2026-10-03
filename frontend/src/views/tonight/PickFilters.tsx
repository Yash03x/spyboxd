'use client';

import Link from 'next/link';

const GENRES = ['Action', 'Adventure', 'Animation', 'Comedy', 'Crime', 'Documentary', 'Drama', 'Family', 'Fantasy', 'History', 'Horror', 'Music', 'Mystery', 'Romance', 'Science Fiction', 'TV Movie', 'Thriller', 'War', 'Western'];
const RUNTIMES = [90, 120, 150, 180];

export interface PickPreferences {
  maxRuntime?: number;
  genre?: string;
  availability?: string;
  rewatch: 'allow' | 'unseen';
}

export function readPickPreferences(params: { get: (key: string) => string | null }): PickPreferences {
  const minutes = Number(params.get('max_runtime'));
  const genre = GENRES.find((value) => value.toLowerCase() === params.get('genre')?.trim().toLowerCase());
  const availability = params.get('availability') ?? '';
  return {
    maxRuntime: Number.isInteger(minutes) && minutes >= 1 && minutes <= 1000 ? minutes : undefined,
    genre,
    availability: ['flatrate', 'rent', 'buy'].includes(availability) ? availability : undefined,
    rewatch: params.get('rewatch') === 'unseen' ? 'unseen' : 'allow',
  };
}

export default function PickFilters({ value, onChange, resetHref, pending }: {
  value: PickPreferences;
  onChange: (key: string, value: string) => void;
  resetHref: string;
  pending: boolean;
}) {
  const runtimes = [...new Set([...RUNTIMES, ...(value.maxRuntime ? [value.maxRuntime] : [])])].sort((a, b) => a - b);
  const fields = [
    { key: 'rewatch', label: 'Rewatches', selected: value.rewatch, options: [['allow', 'Rewatches welcome'], ['unseen', 'Nobody has seen it']] },
    { key: 'max_runtime', label: 'Maximum runtime', selected: String(value.maxRuntime ?? ''), options: [['', 'Any length'], ...runtimes.map((minutes) => [String(minutes), `${minutes} minutes`])] },
    { key: 'genre', label: 'Genre', selected: value.genre ?? '', options: [['', 'All genres'], ...GENRES.map((genre) => [genre, genre])] },
    { key: 'availability', label: 'Watch options', selected: value.availability ?? '', options: [['', 'Any availability'], ['flatrate', 'Subscription streaming'], ['rent', 'Rent'], ['buy', 'Buy']] },
  ];
  return (
    <div aria-label="Recommendation filters" className="flex flex-wrap items-end gap-3 border-b border-term-rule bg-term-bg2 px-[14px] py-3">
      {fields.map((field) => (
        <label key={field.key} className="flex min-w-0 flex-col gap-1 font-term-sans text-t11 text-term-ink3">
          {field.label}
          <select
            aria-label={field.label}
            value={field.selected}
            disabled={pending}
            onChange={(event) => onChange(field.key, event.target.value)}
            className="max-w-full rounded-[3px] border border-term-rule bg-term-bg px-2 py-2 font-term-sans text-t115 text-term-ink"
          >
            {field.options.map(([option, label]) => <option key={option} value={option}>{label}</option>)}
          </select>
        </label>
      ))}
      <Link href={resetHref} scroll={false} aria-disabled={pending} onClick={(event) => { if (pending) event.preventDefault(); }} className="px-2 py-2 font-term-sans text-t11 text-term-accent">Clear filters</Link>
      {pending ? <span role="status" className="font-term-sans text-t11 text-term-muted">Updating filters…</span> : null}
      <p className="m-0 w-full font-term-sans text-t105 text-term-muted">Filters apply to the shortlist. Missing runtime or genre data cannot satisfy a filter; availability reflects the last recorded offers.</p>
    </div>
  );
}
