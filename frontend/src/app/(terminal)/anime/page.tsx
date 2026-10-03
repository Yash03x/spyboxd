'use client';

import { Suspense } from 'react';
import AnimeWorkspace from '../../../views/anime/AnimeWorkspace';

export default function AnimePage() {
  return <Suspense fallback={null}><AnimeWorkspace /></Suspense>;
}
