'use client';

import { useQuery } from '@tanstack/react-query';

import { profileApi } from '../services/api';
import { useAdminScope } from './useAdminScope';

/**
 * Profiles for the caller's active data scope: the personal monitoring set by
 * default, or the full managed library when an admin selects the global view.
 */
export function useScopedProfiles() {
  const { effectiveScope, isGlobalAdminView, userReady } = useAdminScope();

  return useQuery({
    queryKey: ['profiles', effectiveScope],
    queryFn: () => (isGlobalAdminView ? profileApi.getProfiles() : profileApi.getTrackedProfiles()),
    enabled: userReady,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
}
