'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

import TerminalShell from '../../../components/terminal/TerminalShell';
import SelectionBar, { ClosenessPicker } from '../../../components/terminal/SelectionBar';
import { getSection, getTab } from '../../../components/terminal/sections';
import { useTerminalSelection } from '../../../hooks/useTerminalSelection';
import EchoesTab from '../../../views/overlaps/EchoesTab';
import HowSureTab from '../../../views/overlaps/HowSureTab';
import TogetherTab from '../../../views/overlaps/TogetherTab';
import WhenTab from '../../../views/overlaps/WhenTab';

const DEFAULT_GAP_DAYS = 1;

function OverlapsSection() {
  const section = getSection('overlaps');
  const searchParams = useSearchParams();
  const tab = getTab(section, searchParams.get('tab'));
  const selection = useTerminalSelection({ minSelection: 2 });

  // An absent `close` means "use the default", not zero. `Number(null)` is 0,
  // which silently pinned every first visit to the same-day tier and made the
  // control look like it had been chosen for you.
  const closeParam = searchParams.get('close');
  const parsedClose = closeParam === null ? Number.NaN : Number(closeParam);
  const gapDays = Number.isFinite(parsedClose) && parsedClose >= 0 ? parsedClose : DEFAULT_GAP_DAYS;

  const controls = (
    <SelectionBar
      profiles={selection.available}
      selected={selection.selected}
      hrefFor={selection.toggleHref}
      isLocked={selection.isLockedByMinimum}
    >
      {/* Closeness changes what Together and When compute. How sure reports
          coverage, which no window can alter — and Echoes measures a
          fortnight either side by construction (its window is
          `max(closeness, 14)`, and the picker's largest value is 7), so
          offering the control there promised an effect it cannot have. */}
      {tab.id === 'sure' || tab.id === 'echoes' ? null : (
        <ClosenessPicker
          value={gapDays}
          hrefFor={(value) => selection.paramHref('close', String(value))}
        />
      )}
    </SelectionBar>
  );

  return (
    <TerminalShell section={section} tabId={tab.id} controls={controls}>
      {tab.id === 'together' ? (
        <TogetherTab profiles={selection.selected} gapDays={gapDays} />
      ) : null}
      {tab.id === 'echoes' ? <EchoesTab profiles={selection.selected} gapDays={gapDays} /> : null}
      {tab.id === 'when' ? <WhenTab profiles={selection.selected} gapDays={gapDays} /> : null}
      {tab.id === 'sure' ? <HowSureTab profiles={selection.selected} /> : null}
    </TerminalShell>
  );
}

export default function OverlapsPage() {
  return (
    <Suspense fallback={null}>
      <OverlapsSection />
    </Suspense>
  );
}
