'use client';

import { useId, useState } from 'react';
import { EyeOff } from 'lucide-react';

interface SpoilerReviewTextProps {
  text: string;
  containsSpoilers: boolean;
  reviewLabel: string;
  className?: string;
}

function SpoilerReveal({
  text,
  reviewLabel,
  className = '',
}: Omit<SpoilerReviewTextProps, 'containsSpoilers'>) {
  const [revealed, setRevealed] = useState(false);
  const reviewId = useId();

  return (
    <div>
      <button
        type="button"
        aria-controls={reviewId}
        aria-expanded={revealed}
        aria-label={`${revealed ? 'Hide' : 'Reveal'} spoiler review for ${reviewLabel}`}
        onClick={() => setRevealed((isRevealed) => !isRevealed)}
        className="inline-flex items-center gap-2 rounded-lg border border-cinema-400/25 bg-cinema-500/[0.08] px-3 py-2 text-left text-xs font-medium text-cinema-300 transition-colors hover:bg-cinema-500/[0.14] focus:outline-none focus-visible:ring-2 focus-visible:ring-cinema-300/80"
      >
        <EyeOff className="h-4 w-4 shrink-0" aria-hidden="true" />
        <span>Review contains spoilers · {revealed ? 'Hide review' : 'Reveal review'}</span>
      </button>
      <div id={reviewId} hidden={!revealed}>
        {revealed ? <p className={`mt-3 ${className}`}>{text}</p> : null}
      </div>
    </div>
  );
}

export default function SpoilerReviewText(props: SpoilerReviewTextProps) {
  if (!props.containsSpoilers) {
    return <p className={props.className ?? ''}>{props.text}</p>;
  }

  const reviewIdentity = `${props.reviewLabel}\u0000${props.text}`;
  return (
    <SpoilerReveal
      key={reviewIdentity}
      text={props.text}
      reviewLabel={props.reviewLabel}
      className={props.className}
    />
  );
}
