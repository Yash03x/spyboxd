'use client';

import { useQuery } from '@tanstack/react-query';

import { authApi } from '../services/api';

export function useCurrentUser(enabled = true) {
  return useQuery({
    queryKey: ['current-user'],
    queryFn: authApi.getCurrentUser,
    enabled,
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
}
