'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getRecommendationEvaluation } from '../../services/researchApi';
import Rows, { cell } from '../../components/terminal/bodies/Rows';
import { panelState } from '../../components/terminal/states';

const rating = (value: number | null) => value === null ? '—' : `${value.toFixed(2)}★`;

/** Load the diagnostic only when someone asks for it; never delay the picks. */
export default function RecommendationEvaluation({ profiles }: { profiles: string[] }) {
  const [open, setOpen] = useState(false);
  const query = useQuery({
    queryKey: ['recommendation-evaluation', profiles],
    queryFn: () => getRecommendationEvaluation(profiles),
    enabled: open && profiles.length >= 2,
    staleTime: 5 * 60_000,
  });
  const data = query.data;
  return <details className="border-t border-term-rule p-3 font-term-sans text-t11" onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary className="cursor-pointer py-2 text-term-accent">Test the rating component against held-out ratings</summary>
    <p>This diagnostic is separate from the filtered shortlist. It checks the group&apos;s recorded ratings, not predictions about unseen films.</p>
    {open ? panelState({
      isLoading: query.isLoading, error: query.error, isEmpty: !data,
      onRetry: () => query.refetch(),
      empty: { title: 'Choose at least two profiles', body: 'Testing a group requires ratings from more than one member.' },
    }) ?? <>
      <p>{data!.members_evaluated} of {data!.members_selected} members have enough shared ratings for this test. {data!.status === 'insufficient_data' ? 'At least 10 commonly rated films are needed per member; no score is invented for missing evidence.' : `Equal-member result: ${rating(data!.equal_member_mean)}. Lowest member result: ${rating(data!.worst_member_mean)}. Mean-rating-only baseline: ${rating(data!.baseline_equal_member_mean)}.`}</p>
      <Rows columns="minmax(110px,1fr) 65px 85px 85px 75px" head={['MEMBER', 'ELIGIBLE', 'HELD OUT', 'BASELINE', 'BELOW 3★']} rows={data!.per_profile.map((person) => ({ cells: [
        cell(`@${person.username}`, { wrap: true }), cell(person.eligible_movies), cell(rating(person.held_out_mean)), cell(rating(person.mean_only_baseline)), cell(person.evaluated ? `${person.low_rated_picks} / ${person.picks}` : '—'),
      ] }))} />
      <details className="mt-3"><summary className="cursor-pointer text-term-accent">Inspect the films used in this test</summary>{data!.per_profile.filter((person) => person.evaluated).map((person) => <p key={person.username}><strong>@{person.username}:</strong> {person.examples.map((film) => `${film.title} (${rating(film.held_out_rating)})`).join('; ')}.</p>)}</details>
      <p className="text-term-muted">{data!.method}</p>
      <p className="text-term-accent">{data!.limitations}</p>
    </> : null}
  </details>;
}
