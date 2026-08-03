'use client';

import { Suspense } from 'react';
import TerminalShell from '../../../components/terminal/TerminalShell';
import { getSection } from '../../../components/terminal/sections';
import OverviewTab from '../../../views/overview/OverviewTab';

export default function OverviewPage() {
  const section = getSection('overview');
  return (
    <Suspense fallback={null}>
      <TerminalShell section={section}>
        <OverviewTab />
      </TerminalShell>
    </Suspense>
  );
}
