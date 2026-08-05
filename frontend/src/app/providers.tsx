'use client';

import { useAuth } from '@clerk/nextjs';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Image from 'next/image';
import { useEffect, useState } from 'react';
import { setApiTokenProvider } from '../services/api';

export default function Providers({ children }: { children: React.ReactNode }) {
  const { getToken, isLoaded, isSignedIn, sessionId, userId } = useAuth();

  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            refetchOnWindowFocus: false,
            retry: 1,
            staleTime: 5 * 60 * 1000,
          },
        },
      })
  );

  const authScope = isLoaded
    ? `${isSignedIn ? userId ?? 'signed-in' : 'signed-out'}:${sessionId ?? 'no-session'}`
    : null;
  const [readyScope, setReadyScope] = useState<string | null>(null);

  useEffect(() => {
    if (!authScope) {
      setApiTokenProvider(null);
      setReadyScope(null);
      return;
    }

    // Never retain one account's cached responses after Clerk changes users or
    // sessions. Install the token source before mounting query consumers.
    queryClient.clear();
    setApiTokenProvider(
      isSignedIn
        ? async () => (await getToken()) ?? null
        : null,
    );
    setReadyScope(authScope);

    return () => {
      setApiTokenProvider(null);
      queryClient.clear();
    };
  }, [authScope, getToken, isSignedIn, queryClient]);

  const authReady = Boolean(authScope && readyScope === authScope);

  return (
    <QueryClientProvider client={queryClient}>
      {authReady ? children : (
        <main className="grid min-h-screen place-items-center px-6" aria-live="polite">
          <div className="text-center">
            <Image
              src="/icon.svg"
              alt=""
              width={48}
              height={48}
              className="mx-auto h-12 w-12 rounded-xl border border-term-rule"
              priority
            />
            <p className="mt-4 text-sm text-white/55">Preparing Spyboxd…</p>
          </div>
        </main>
      )}
    </QueryClientProvider>
  );
}
