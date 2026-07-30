'use client';

import { useQuery } from '@tanstack/react-query';

import { authApi } from '../services/api';

export function useCurrentUser() {
  return useQuery({
    queryKey: ['current-user'],
    queryFn: authApi.getCurrentUser,
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
}
