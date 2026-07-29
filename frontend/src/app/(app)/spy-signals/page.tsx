import { Suspense } from 'react';
import SpySignals from '../../../views/SpySignals';

export default function SpySignalsPage() {
  return (
    <Suspense>
      <SpySignals />
    </Suspense>
  );
}
