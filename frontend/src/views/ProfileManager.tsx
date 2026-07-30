'use client';

import React, { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams, useRouter } from 'next/navigation';
import {
  CheckCircleIcon,
  ClockIcon,
  ExclamationTriangleIcon,
  MagnifyingGlassIcon,
  PlusIcon,
  TrashIcon,
  UserCircleIcon,
} from '@heroicons/react/24/outline';
import { FileArchive, Send, ShieldCheck, Upload, UserPlus, Users } from 'lucide-react';
import {
  adminProfileRequestApi,
  profileApi,
  type ProfileRequestStatus,
} from '../services/api';
import { useCurrentUser } from '../hooks/useCurrentUser';
import LoadingSpinner from '../components/LoadingSpinner';
import ErrorMessage from '../components/ErrorMessage';
import { ProfileAvatar } from '../components/insights/InsightUI';
import toast from 'react-hot-toast';

const REQUEST_STATUS_COPY: Record<ProfileRequestStatus, { label: string; description: string; className: string }> = {
  pending: {
    label: 'Awaiting review',
    description: 'An admin will review this username.',
    className: 'border-amber-400/25 bg-amber-400/10 text-amber-200',
  },
  approved: {
    label: 'Accepted',
    description: 'Queued for the next residential full sync.',
    className: 'border-blue-400/25 bg-blue-400/10 text-blue-200',
  },
  fulfilled: {
    label: 'Added',
    description: 'The sync completed and this profile is now available.',
    className: 'border-emerald-400/25 bg-emerald-400/10 text-emerald-200',
  },
  rejected: {
    label: 'Not approved',
    description: 'This request will not be synced.',
    className: 'border-red-400/25 bg-red-400/10 text-red-200',
  },
};

const PROFILE_CATALOG_RESULT_LIMIT = 100;
const PROFILE_CATALOG_SEARCH_DELAY_MS = 250;


const ProfileManager: React.FC = () => {
  const searchParams = useSearchParams();
  const router = useRouter();
  const currentUserQuery = useCurrentUser();
  const isAdmin = currentUserQuery.data?.is_admin ?? false;

  const [searchTerm, setSearchTerm] = useState('');
  const [catalogSearchTerm, setCatalogSearchTerm] = useState('');
  const [debouncedCatalogSearchTerm, setDebouncedCatalogSearchTerm] = useState('');
  const [requestedUsername, setRequestedUsername] = useState('');
  const [isAddingProfile, setIsAddingProfile] = useState(false);
  const [newProfileUsername, setNewProfileUsername] = useState('');
  const [filterStatus, setFilterStatus] = useState<string>('all');
  const [deletingProfile, setDeletingProfile] = useState<string | null>(null);
  const [untrackingProfile, setUntrackingProfile] = useState<string | null>(null);
  const [trackingProfileId, setTrackingProfileId] = useState<number | null>(null);
  const [adminNotes, setAdminNotes] = useState<Record<number, string>>({});
  const [residentialSyncFiles, setResidentialSyncFiles] = useState<FileList | null>(null);
  const [exportFiles, setExportFiles] = useState<FileList | null>(null);
  const [hasOwnerPublishingConsent, setHasOwnerPublishingConsent] = useState(false);
  const residentialSyncInputRef = useRef<HTMLInputElement>(null);
  const exportInputRef = useRef<HTMLInputElement>(null);

  const queryClient = useQueryClient();

  useEffect(() => {
    if (isAdmin && searchParams.get('add') === 'true') {
      setIsAddingProfile(true);
      router.replace('/profiles');
    }
  }, [isAdmin, searchParams, router]);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      setDebouncedCatalogSearchTerm(catalogSearchTerm.trim());
    }, PROFILE_CATALOG_SEARCH_DELAY_MS);

    return () => window.clearTimeout(timeoutId);
  }, [catalogSearchTerm]);

  const { data: profiles, isLoading, error } = useQuery({
    queryKey: ['profiles'],
    queryFn: profileApi.getProfiles,
    enabled: currentUserQuery.isSuccess,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const adminTrackedProfilesQuery = useQuery({
    queryKey: ['profiles', 'tracked', 'profile-manager'],
    queryFn: profileApi.getTrackedProfiles,
    enabled: currentUserQuery.isSuccess && isAdmin,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const profileRequestsQuery = useQuery({
    queryKey: ['profile-requests'],
    queryFn: profileApi.getRequests,
    enabled: currentUserQuery.isSuccess,
    staleTime: 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const profileCatalogQuery = useQuery({
    queryKey: ['profile-catalog', debouncedCatalogSearchTerm],
    queryFn: () => profileApi.getCatalog(
      debouncedCatalogSearchTerm,
      PROFILE_CATALOG_RESULT_LIMIT,
    ),
    enabled: currentUserQuery.isSuccess,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const adminRequestsQuery = useQuery({
    queryKey: ['admin-profile-requests'],
    queryFn: () => adminProfileRequestApi.getRequests(),
    enabled: currentUserQuery.isSuccess && isAdmin,
    staleTime: 30 * 1000,
    refetchOnWindowFocus: false,
  });

  const refreshProfileSurfaces = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: ['profiles'] }),
    queryClient.invalidateQueries({ queryKey: ['profile-catalog'] }),
    queryClient.invalidateQueries({ queryKey: ['profile-requests'] }),
    queryClient.invalidateQueries({ queryKey: ['admin-profile-requests'] }),
    queryClient.invalidateQueries({ queryKey: ['dashboard-analytics'] }),
    queryClient.invalidateQueries({ queryKey: ['recent-changes'] }),
  ]);

  const requestProfileMutation = useMutation({
    mutationFn: profileApi.requestProfile,
    onSuccess: (result) => {
      void refreshProfileSurfaces();
      setRequestedUsername('');
      toast.success(
        result.status === 'tracked'
          ? 'Profile added to My Profiles.'
          : 'Request sent. You can follow its status below.',
      );
    },
    onError: (requestError: Error) => {
      toast.error(`Could not submit profile: ${requestError.message}`);
    },
  });

  const trackCatalogProfileMutation = useMutation({
    mutationFn: async (profileId: number) => {
      setTrackingProfileId(profileId);
      return profileApi.trackExisting(profileId);
    },
    onSuccess: (result) => {
      void refreshProfileSurfaces();
      setTrackingProfileId(null);
      toast.success(`${result.profile.username} added to your monitored profiles.`);
    },
    onError: (trackError: Error) => {
      setTrackingProfileId(null);
      toast.error(`Could not monitor profile: ${trackError.message}`);
    },
  });

  const untrackProfileMutation = useMutation({
    mutationFn: async (username: string) => {
      setUntrackingProfile(username);
      return profileApi.stopTracking(username);
    },
    onSuccess: () => {
      void refreshProfileSurfaces();
      setUntrackingProfile(null);
      toast.success('Profile removed from My Profiles. Its shared data was not deleted.');
    },
    onError: (untrackError: Error) => {
      setUntrackingProfile(null);
      toast.error(`Could not remove profile: ${untrackError.message}`);
    },
  });

  const reviewRequestMutation = useMutation({
    mutationFn: ({ id, status }: { id: number; status: Extract<ProfileRequestStatus, 'approved' | 'rejected'> }) => (
      adminProfileRequestApi.updateRequest(id, status, adminNotes[id]?.trim() || undefined)
    ),
    onSuccess: (result) => {
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: ['admin-profile-requests'] }),
        queryClient.invalidateQueries({ queryKey: ['profile-requests'] }),
      ]);
      setAdminNotes((notes) => {
        const next = { ...notes };
        delete next[result.request.id];
        return next;
      });
      toast.success(
        result.request.status === 'approved'
          ? 'Request accepted for the next residential sync.'
          : 'Request rejected.',
      );
    },
    onError: (reviewError: Error) => {
      toast.error(`Could not update request: ${reviewError.message}`);
    },
  });

  const addProfileMutation = useMutation({
    mutationFn: profileApi.createProfile,
    onSuccess: () => {
      void refreshProfileSurfaces();
      setIsAddingProfile(false);
      setNewProfileUsername('');
      toast.success('Profile added successfully.');
    },
    onError: (error: Error) => {
      toast.error(`Failed to add profile: ${error.message}`);
    },
  });

  const deleteProfileMutation = useMutation({
    mutationFn: async (username: string) => {
      setDeletingProfile(username);
      return profileApi.deleteProfile(username);
    },
    onSuccess: () => {
      void refreshProfileSurfaces();
      toast.success('Profile deleted successfully.');
      setDeletingProfile(null);
    },
    onError: (error: Error) => {
      toast.error(`Failed to delete profile: ${error.message}`);
      setDeletingProfile(null);
    },
  });

  const residentialSyncUploadMutation = useMutation({
    mutationFn: (files: FileList) => profileApi.uploadFiles(files, {
      publish_owner_data: false,
      require_full_sync: true,
    }),
    onSuccess: (result) => {
      void refreshProfileSurfaces();
      const loadedCount = result.loaded_profiles.length;
      const sourceKinds = Array.from(new Set((result.imports ?? []).map((item) => item.source_kind)));
      const provenanceCopy = sourceKinds.length > 0 ? ` Provenance: ${sourceKinds.join(', ')}.` : '';
      if (loadedCount > 0) {
        toast.success(`${loadedCount} residential full-sync bundle${loadedCount === 1 ? '' : 's'} imported.${provenanceCopy}`);
      }
      if (result.errors?.length) toast.error(result.errors.join(' '));
      setResidentialSyncFiles(null);
      if (residentialSyncInputRef.current) residentialSyncInputRef.current.value = '';
    },
    onError: (uploadError: Error) => {
      toast.error(`Residential sync upload failed: ${uploadError.message}`);
    },
  });

  const exportUploadMutation = useMutation({
    mutationFn: (files: FileList) => profileApi.uploadFiles(files, { publish_owner_data: true }),
    onSuccess: (result) => {
      void refreshProfileSurfaces();
      const loadedCount = result.loaded_profiles.length;
      const sourceKinds = Array.from(new Set((result.imports ?? []).map((item) => item.source_kind)));
      const provenanceCopy = sourceKinds.length > 0 ? ` Provenance: ${sourceKinds.join(', ')}.` : '';
      toast.success(`${loadedCount} owner export${loadedCount === 1 ? '' : 's'} imported.${provenanceCopy}`);
      if (result.errors?.length) toast.error(result.errors.join(' '));
      setExportFiles(null);
      setHasOwnerPublishingConsent(false);
      if (exportInputRef.current) exportInputRef.current.value = '';
    },
    onError: (uploadError: Error) => {
      toast.error(`Export upload failed: ${uploadError.message}`);
    },
  });

  const profilesArray = Array.isArray(profiles) ? profiles : [];
  const catalogProfiles = profileCatalogQuery.data?.profiles ?? [];
  const catalogTotal = profileCatalogQuery.data?.total ?? 0;
  const catalogResultLimit = profileCatalogQuery.data?.limit ?? PROFILE_CATALOG_RESULT_LIMIT;
  const catalogProfileNoun = catalogTotal === 1 ? 'profile' : 'profiles';
  const isCatalogSearchPending = catalogSearchTerm.trim() !== debouncedCatalogSearchTerm;
  const monitoredProfileCount = isAdmin
    ? adminTrackedProfilesQuery.data?.length
    : profilesArray.length;
  const normalizedRequestedUsername = requestedUsername.trim().replace(/^@/, '');
  const primaryUsername = currentUserQuery.data?.letterboxd_username ?? null;
  const primaryProfileStatus = currentUserQuery.data?.primary_profile_status ?? 'unconfigured';
  const isPrimaryUsername = (username: string) => (
    primaryUsername !== null && username.toLowerCase() === primaryUsername.toLowerCase()
  );
  const filteredProfiles = profilesArray.filter((profile) => {
    const matchesSearch = profile.username.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesFilter =
      filterStatus === 'all' ||
      (filterStatus === 'synced' && profile.scraping_status === 'completed') ||
      (filterStatus === 'pending' && profile.scraping_status !== 'completed') ||
      (filterStatus === 'error' && profile.scraping_status === 'error');
    return matchesSearch && matchesFilter;
  });

  const getStatusBadge = (status?: string) => {
    if (status === 'completed') {
      return {
        label: 'full sync',
        className: 'bg-green-500/20 text-green-400 border-green-500/30',
        icon: <CheckCircleIcon className="w-3 h-3 mr-1" />,
      };
    }

    if (status === 'error') {
      return {
        label: 'error',
        className: 'bg-red-500/20 text-red-400 border-red-500/30',
        icon: <ExclamationTriangleIcon className="w-3 h-3 mr-1" />,
      };
    }

    return {
      label: 'awaiting sync',
      className: 'bg-amber-500/20 text-amber-300 border-amber-400/30',
      icon: <ClockIcon className="w-3 h-3 mr-1" />,
    };
  };

  if (isLoading || currentUserQuery.isLoading) return <LoadingSpinner />;
  if (error || currentUserQuery.error) return <ErrorMessage message="Failed to load your profiles" />;

  return (
    <motion.div
      className="space-y-8"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6 }}
    >
      <motion.div
        className="flex items-center justify-between"
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
      >
        <div>
          <h1 className="text-4xl font-bold text-white text-glow mb-2">
            {isAdmin ? 'Profiles' : 'My Profiles'}
          </h1>
          <p className="text-white/60">
            {isAdmin
              ? 'Manage the shared profile library, requests, and residential sync workflow.'
              : 'Choose the Letterboxd profiles that power your dashboard and comparisons.'}
          </p>
        </div>

        {isAdmin && (
          <motion.button
            onClick={() => setIsAddingProfile(true)}
            className="btn-primary flex items-center space-x-2"
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
          >
            <UserPlus className="w-5 h-5" />
            <span>Admin add placeholder</span>
          </motion.button>
        )}
      </motion.div>

      {(primaryUsername || searchParams.get('onboarding') === '1') && (
        <motion.section
          className="rounded-2xl border border-cinema-400/25 bg-cinema-500/10 p-5"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.22 }}
          aria-labelledby="primary-profile-status-title"
          data-testid="primary-profile-status"
        >
          <div className="flex items-start gap-4">
            <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl border border-cinema-400/30 bg-black/15 text-cinema-200">
              <ShieldCheck className="h-5 w-5" />
            </span>
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-cinema-300">Your Spyboxd identity</p>
              <h2 id="primary-profile-status-title" className="mt-1 text-xl font-bold text-white">
                {primaryUsername ? `@${primaryUsername}` : 'Letterboxd username not linked'}
              </h2>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-white/60">
                {primaryProfileStatus === 'tracked' && 'Your Letterboxd profile is synced and included in your monitored profiles.'}
                {primaryProfileStatus === 'pending' && 'We automatically requested this profile. It is awaiting review before a residential full sync.'}
                {primaryProfileStatus === 'approved' && 'Your profile request is approved and queued for the next residential full sync.'}
                {primaryProfileStatus === 'rejected' && 'This profile request was not approved. Contact the administrator if this is the correct Letterboxd username.'}
                {primaryProfileStatus === 'available' && 'This profile is already synced and can be added from the profile list below.'}
                {primaryProfileStatus === 'unlinked' && 'This username is linked to your account, but its Letterboxd profile has not been requested yet.'}
                {primaryProfileStatus === 'unconfigured' && 'This pre-existing account has no Letterboxd username linked. Contact the administrator to repair the account identity.'}
              </p>
            </div>
          </div>
        </motion.section>
      )}

      <motion.section
        className="card-cinema"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.25 }}
        aria-labelledby="profile-catalog-title"
      >
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-3">
              <h2 id="profile-catalog-title" className="text-xl font-bold text-white">Choose profiles to monitor</h2>
              <span className="rounded-lg border border-cinema-400/25 bg-cinema-500/10 px-2.5 py-1 text-xs font-semibold text-cinema-200">
                {isAdmin && adminTrackedProfilesQuery.error
                  ? 'Monitoring count unavailable'
                  : `${monitoredProfileCount ?? '…'} monitored`}
              </span>
            </div>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-white/60">
              Select any synced profile already in Spyboxd. Your choices are private to your account, power the Monitored view in My Dashboard, and can be changed at any time.
              {isAdmin ? ' The default global admin dashboard and library controls remain explicit and separate.' : ''}
            </p>
          </div>
          <label className="relative w-full lg:max-w-sm">
            <span className="sr-only">Search available profiles</span>
            <MagnifyingGlassIcon className="absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-white/40" />
            <input
              type="search"
              placeholder="Search available profiles..."
              value={catalogSearchTerm}
              onChange={(event) => setCatalogSearchTerm(event.target.value)}
              className="input-field w-full pl-10"
            />
          </label>
        </div>

        {profileCatalogQuery.isLoading || profileCatalogQuery.isFetching || isCatalogSearchPending ? (
          <p className="mt-5 text-sm text-white/45">
            {catalogSearchTerm.trim() ? 'Searching synced profiles…' : 'Loading available profiles…'}
          </p>
        ) : profileCatalogQuery.error ? (
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-red-400/20 bg-red-400/5 p-4">
            <p className="text-sm text-red-200">Available profiles could not be loaded.</p>
            <button type="button" onClick={() => void profileCatalogQuery.refetch()} className="btn-secondary px-3 py-2 text-xs">Try again</button>
          </div>
        ) : catalogProfiles.length === 0 ? (
          <p className="mt-5 rounded-xl border border-white/10 bg-black/15 p-4 text-sm text-white/45">
            {catalogSearchTerm.trim() ? 'No synced profiles match that search.' : 'No synced profiles are available yet.'}
          </p>
        ) : (
          <>
            <p className="mt-5 text-xs text-white/45" data-testid="profile-catalog-result-summary">
              {catalogProfiles.length === catalogTotal
                ? `${catalogTotal.toLocaleString()} ${debouncedCatalogSearchTerm ? 'matching ' : ''}synced ${catalogProfileNoun}`
                : `Showing ${catalogProfiles.length.toLocaleString()} of ${catalogTotal.toLocaleString()} ${debouncedCatalogSearchTerm ? 'matching ' : ''}synced ${catalogProfileNoun}`}
              {catalogTotal > catalogProfiles.length
                ? ` · Results are limited to ${catalogResultLimit.toLocaleString()} per search; refine the search to find the rest.`
                : ''}
            </p>
            <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {catalogProfiles.map((profile) => {
                const isBusy = trackingProfileId === profile.id || untrackingProfile === profile.username;
                const isPrimaryProfile = isPrimaryUsername(profile.username);
                return (
                  <article key={profile.id} className="flex min-w-0 items-center gap-3 rounded-xl border border-white/10 bg-black/15 p-3">
                    <ProfileAvatar profile={profile} size="lg" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-semibold text-white">{profile.display_name || profile.username}</p>
                      <p className="truncate text-xs text-white/45">
                        @{profile.username} · {profile.total_films.toLocaleString()} films
                        {isPrimaryProfile ? ' · Your profile' : ''}
                      </p>
                    </div>
                    <button
                      type="button"
                      disabled={isBusy || (isPrimaryProfile && profile.is_tracked)}
                      onClick={() => {
                        if (profile.is_tracked) {
                          untrackProfileMutation.mutate(profile.username);
                        } else {
                          trackCatalogProfileMutation.mutate(profile.id);
                        }
                      }}
                      aria-label={isPrimaryProfile && profile.is_tracked
                        ? `Your Letterboxd profile ${profile.username}`
                        : `${profile.is_tracked ? 'Stop monitoring' : 'Monitor'} ${profile.username}`}
                      className={profile.is_tracked
                        ? 'rounded-lg border border-emerald-400/25 bg-emerald-400/10 px-3 py-2 text-xs font-semibold text-emerald-200 transition-colors hover:bg-emerald-400/20 disabled:opacity-50'
                        : 'rounded-lg border border-cinema-400/25 bg-cinema-500/10 px-3 py-2 text-xs font-semibold text-cinema-200 transition-colors hover:bg-cinema-500/20 disabled:opacity-50'}
                    >
                      {isBusy ? 'Saving…' : isPrimaryProfile && profile.is_tracked ? 'Your profile' : profile.is_tracked ? 'Monitoring' : 'Monitor'}
                    </button>
                  </article>
                );
              })}
            </div>
          </>
        )}
      </motion.section>

      <motion.section
        className="card-cinema"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
      >
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(22rem,.75fr)] lg:items-end">
          <div>
            <div className="flex items-start gap-3">
              <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl border border-cinema-400/25 bg-cinema-500/10 text-cinema-300">
                <UserPlus className="h-5 w-5" />
              </span>
              <div>
                <h2 className="text-xl font-bold text-white">Request another profile</h2>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-white/60">
                  Enter a Letterboxd username that Spyboxd does not have yet. It will be sent for review and, once accepted, queued for the next residential full sync.
                </p>
              </div>
            </div>
          </div>
          <form
            className="flex flex-col gap-3 sm:flex-row"
            onSubmit={(event) => {
              event.preventDefault();
              if (normalizedRequestedUsername) requestProfileMutation.mutate(normalizedRequestedUsername);
            }}
          >
            <label className="min-w-0 flex-1">
              <span className="sr-only">Letterboxd username</span>
              <input
                type="text"
                placeholder="Letterboxd username"
                value={requestedUsername}
                onChange={(event) => setRequestedUsername(event.target.value)}
                className="input-field w-full"
                autoComplete="off"
                maxLength={16}
                pattern="@?[A-Za-z0-9_]{2,15}"
                title="Use 2–15 letters, numbers, or underscores."
              />
            </label>
            <button
              type="submit"
              disabled={!normalizedRequestedUsername || requestProfileMutation.isPending}
              className="btn-primary flex min-h-11 items-center justify-center gap-2 px-5"
            >
              {requestProfileMutation.isPending ? <ClockIcon className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              {requestProfileMutation.isPending ? 'Submitting…' : 'Add or request'}
            </button>
          </form>
        </div>
      </motion.section>

      {(profileRequestsQuery.isLoading || profileRequestsQuery.error || (profileRequestsQuery.data?.length ?? 0) > 0) && (
        <motion.section
          className="card-cinema"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.32 }}
          aria-labelledby="my-request-status-title"
        >
          <div className="flex items-center justify-between gap-4">
            <div>
              <h2 id="my-request-status-title" className="text-lg font-bold text-white">My request status</h2>
              <p className="mt-1 text-sm text-white/55">Approval accepts a username for sync; the profile appears only after that sync finishes.</p>
            </div>
            {profileRequestsQuery.isFetching && <ClockIcon className="h-5 w-5 animate-spin text-white/35" />}
          </div>
          {profileRequestsQuery.error ? (
            <p className="mt-4 text-sm text-red-300">Request history could not be loaded.</p>
          ) : (
            <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {(profileRequestsQuery.data ?? []).map((request) => {
                const status = REQUEST_STATUS_COPY[request.status];
                return (
                  <article key={request.id} className="rounded-xl border border-white/10 bg-black/15 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="font-semibold text-white">@{request.requested_username}</p>
                        <p className="mt-1 text-xs text-white/40">Requested {new Date(request.requested_at).toLocaleDateString()}</p>
                      </div>
                      <span className={`rounded-lg border px-2.5 py-1 text-xs font-semibold ${status.className}`}>{status.label}</span>
                    </div>
                    <p className="mt-3 text-sm text-white/55">{status.description}</p>
                  </article>
                );
              })}
            </div>
          )}
        </motion.section>
      )}

      {isAdmin && (
        <motion.section
          className="card-cinema"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.34 }}
          aria-labelledby="admin-sync-workflow-title"
        >
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(22rem,.8fr)] xl:items-start">
            <div className="space-y-2">
              <h2 id="admin-sync-workflow-title" className="text-xl font-bold text-white">Residential Sync Workflow</h2>
              <p className="text-sm text-white/70">VPS scraping is disabled. Full profile syncs come only from the local residential runner.</p>
              <div className="rounded-xl border border-white/10 bg-noir-900/60 px-4 py-3 text-sm text-white/80">
                <p>1. Approve pending requests that should enter the sync queue.</p>
                <p>2. Update `sync-profiles.json` on the residential machine.</p>
                <p>3. Run `.venv/bin/python scripts/batch_full_sync.py --config sync-profiles.json`.</p>
                <p>4. Upload the resulting ZIP bundles here if the runner did not upload them directly.</p>
              </div>
            </div>

            <div className="rounded-xl border border-cinema-400/20 bg-cinema-500/5 p-4" data-testid="residential-sync-upload">
              <label className="block">
                <span className="block text-sm font-semibold text-white">Residential full-sync ZIP bundles</span>
                <span className="mt-1 block text-xs leading-5 text-white/50">
                  Upload one or more schema-v2 bundles produced from public Letterboxd HTML. Owner-export publishing stays off for this import.
                </span>
                <input
                  ref={residentialSyncInputRef}
                  type="file"
                  accept=".zip,application/zip"
                  multiple
                  aria-label="Residential full-sync ZIP bundles"
                  disabled={residentialSyncUploadMutation.isPending}
                  onChange={(event) => setResidentialSyncFiles(event.target.files)}
                  className="mt-3 block w-full text-xs text-white/50 file:mr-3 file:cursor-pointer file:rounded-lg file:border file:border-white/10 file:bg-white/5 file:px-3 file:py-2 file:text-xs file:font-semibold file:text-white/70 hover:file:bg-white/10"
                />
              </label>
              <p className="mt-3 flex items-start gap-2 text-xs leading-5 text-white/45">
                <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
                This admin-only path imports public residential snapshots. Use the separate owner-export workflow below for private or deleted account data.
              </p>
              <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-[11px] text-white/35">
                  {residentialSyncFiles?.length
                    ? `${residentialSyncFiles.length} ZIP${residentialSyncFiles.length === 1 ? '' : 's'} selected`
                    : 'A successful upload fulfills matching approved profile requests.'}
                </p>
                <button
                  type="button"
                  onClick={() => {
                    if (residentialSyncFiles?.length) {
                      residentialSyncUploadMutation.mutate(residentialSyncFiles);
                    }
                  }}
                  disabled={!residentialSyncFiles?.length || residentialSyncUploadMutation.isPending}
                  className="btn-primary flex min-h-10 items-center justify-center gap-2 px-4 py-2 text-xs"
                >
                  <Upload className="h-4 w-4" /> {residentialSyncUploadMutation.isPending ? 'Uploading…' : 'Import full sync'}
                </button>
              </div>
            </div>
          </div>
        </motion.section>
      )}

      {isAdmin && (
        <motion.section
          className="card-cinema"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.35 }}
          aria-labelledby="admin-request-queue-title"
        >
          <div>
            <h2 id="admin-request-queue-title" className="text-xl font-bold text-white">Profile request queue</h2>
            <p className="mt-1 text-sm text-white/55">Accepted requests remain visible as awaiting residential sync until an upload fulfills them.</p>
          </div>
          {adminRequestsQuery.isLoading ? (
            <p className="mt-4 text-sm text-white/45">Loading requests…</p>
          ) : adminRequestsQuery.error ? (
            <p className="mt-4 text-sm text-red-300">The admin request queue could not be loaded.</p>
          ) : (adminRequestsQuery.data?.length ?? 0) === 0 ? (
            <p className="mt-4 rounded-xl border border-white/10 bg-black/15 p-4 text-sm text-white/45">No profile requests yet.</p>
          ) : (
            <div className="mt-4 space-y-3">
              {(adminRequestsQuery.data ?? []).map((request) => (
                <article key={request.id} className="grid gap-3 rounded-xl border border-white/10 bg-black/15 p-4 xl:grid-cols-[minmax(0,1fr)_minmax(16rem,.7fr)_auto] xl:items-center">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-semibold text-white">@{request.requested_username}</p>
                      <span className={`rounded-lg border px-2 py-0.5 text-[11px] font-semibold ${REQUEST_STATUS_COPY[request.status].className}`}>
                        {request.status === 'approved' ? 'Awaiting residential sync' : REQUEST_STATUS_COPY[request.status].label}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-white/40">Requester {request.requester_user_id} · {new Date(request.requested_at).toLocaleString()}</p>
                  </div>
                  {request.status === 'pending' ? (
                    <input
                      value={adminNotes[request.id] ?? ''}
                      onChange={(event) => setAdminNotes((notes) => ({ ...notes, [request.id]: event.target.value }))}
                      placeholder="Optional note"
                      className="input-field w-full"
                      aria-label={`Note for ${request.requested_username}`}
                    />
                  ) : (
                    <p className="text-xs text-white/45">{request.note || 'No admin note.'}</p>
                  )}
                  {request.status === 'pending' ? (
                    <div className="flex gap-2">
                      <button
                        type="button"
                        disabled={reviewRequestMutation.isPending}
                        onClick={() => reviewRequestMutation.mutate({ id: request.id, status: 'approved' })}
                        className="rounded-lg border border-emerald-400/25 bg-emerald-400/10 px-3 py-2 text-xs font-semibold text-emerald-200 transition-colors hover:bg-emerald-400/20 disabled:opacity-50"
                      >
                        Accept for sync
                      </button>
                      <button
                        type="button"
                        disabled={reviewRequestMutation.isPending}
                        onClick={() => reviewRequestMutation.mutate({ id: request.id, status: 'rejected' })}
                        className="rounded-lg border border-red-400/25 bg-red-400/10 px-3 py-2 text-xs font-semibold text-red-200 transition-colors hover:bg-red-400/20 disabled:opacity-50"
                      >
                        Reject
                      </button>
                    </div>
                  ) : (
                    <p className="text-xs text-white/40">{REQUEST_STATUS_COPY[request.status].description}</p>
                  )}
                </article>
              ))}
            </div>
          )}
        </motion.section>
      )}

      {isAdmin && (
        <motion.section
          className="card-cinema"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.35 }}
          aria-labelledby="letterboxd-export-title"
        >
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(22rem,.8fr)] xl:items-center">
            <div className="flex items-start gap-4">
              <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl border border-cinema-400/25 bg-cinema-500/10 text-cinema-300">
                <FileArchive className="h-5 w-5" />
              </span>
              <div>
                <h2 id="letterboxd-export-title" className="text-lg font-bold text-white">Optional owner-provided Letterboxd export</h2>
                <p className="mt-2 max-w-3xl text-sm leading-6 text-white/60">
                  A profile owner can opt in by downloading their official Letterboxd export ZIP and sharing it for import. This can add export-only history, tags, private account data, and deleted records that a public profile cannot expose.
                </p>
                <p className="mt-2 flex items-start gap-2 text-xs leading-5 text-white/40">
                  <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
                  Upload only with the account owner&apos;s permission. Export activity dates retain Letterboxd-export provenance and are not relabeled as confirmed viewing dates.
                </p>
              </div>
            </div>

            <div className="rounded-xl border border-white/10 bg-black/15 p-3">
              <label className="block">
                <span className="mb-2 block text-xs font-semibold text-white/55">Official export ZIP</span>
                <input
                  ref={exportInputRef}
                  type="file"
                  accept=".zip,application/zip"
                  multiple
                  disabled={exportUploadMutation.isPending}
                  onChange={(event) => {
                    setExportFiles(event.target.files);
                    setHasOwnerPublishingConsent(false);
                  }}
                  className="block w-full text-xs text-white/50 file:mr-3 file:cursor-pointer file:rounded-lg file:border file:border-white/10 file:bg-white/5 file:px-3 file:py-2 file:text-xs file:font-semibold file:text-white/70 hover:file:bg-white/10"
                />
              </label>
              <label className="mt-4 flex cursor-pointer items-start gap-3 rounded-lg border border-amber-400/20 bg-amber-400/5 p-3 text-xs leading-5 text-white/65">
                <input
                  type="checkbox"
                  checked={hasOwnerPublishingConsent}
                  disabled={exportUploadMutation.isPending}
                  onChange={(event) => setHasOwnerPublishingConsent(event.target.checked)}
                  className="mt-1 h-4 w-4 shrink-0 cursor-pointer accent-orange-500 disabled:cursor-not-allowed"
                />
                <span>
                  I confirm that I have the account owner&apos;s permission and their consent to publish all imported export contents—including private or deleted items—to visitors of this site.
                </span>
              </label>
              <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-[11px] text-white/35">
                  {exportFiles?.length ? `${exportFiles.length} ZIP${exportFiles.length === 1 ? '' : 's'} selected` : 'ZIP files are processed by the authenticated import endpoint.'}
                </p>
                <button
                  type="button"
                  onClick={() => {
                    if (exportFiles?.length && hasOwnerPublishingConsent) {
                      exportUploadMutation.mutate(exportFiles);
                    }
                  }}
                  disabled={!exportFiles?.length || !hasOwnerPublishingConsent || exportUploadMutation.isPending}
                  className="btn-primary flex min-h-10 items-center justify-center gap-2 px-4 py-2 text-xs"
                >
                  <Upload className="h-4 w-4" /> {exportUploadMutation.isPending ? 'Importing…' : 'Import owner export'}
                </button>
              </div>
            </div>
          </div>
        </motion.section>
      )}

      <motion.div
        className="flex flex-col sm:flex-row gap-4 items-center justify-between"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.4 }}
      >
        <div className="flex items-center space-x-4 flex-1">
          <div className="relative flex-1 max-w-md">
            <MagnifyingGlassIcon className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-white/40" />
            <input
              type="text"
              placeholder="Search profiles..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="input-field pl-10 w-full"
            />
          </div>
          <select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value)}
            className="input-field"
          >
            <option value="all">{isAdmin ? 'All managed profiles' : 'All my profiles'}</option>
            <option value="synced">Synced</option>
            <option value="pending">Awaiting Sync</option>
            <option value="error">Error</option>
          </select>
        </div>
        <div className="text-white/60 text-sm">
          {filteredProfiles.length} of {profilesArray.length} {isAdmin ? 'managed' : 'tracked'} profiles
        </div>
      </motion.div>

      <AnimatePresence>
        {isAddingProfile && (
          <motion.div
            className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-[100]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            style={{ isolation: 'isolate' }}
          >
            <motion.div
              className="card-cinema w-full max-w-md relative z-50"
              initial={{ scale: 0.9, y: 20 }}
              animate={{ scale: 1, y: 0 }}
              exit={{ scale: 0.9, y: 20 }}
            >
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-xl font-bold text-white">Add New Profile</h3>
              </div>
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-white/80 mb-2">
                    Letterboxd Username
                  </label>
                  <input
                    type="text"
                    placeholder="e.g., username"
                    value={newProfileUsername}
                    onChange={(e) => setNewProfileUsername(e.target.value)}
                    className="input-field w-full"
                    onKeyDown={(e) => e.key === 'Enter' && addProfileMutation.mutate(newProfileUsername.trim())}
                    autoFocus
                  />
                </div>
                <p className="text-xs text-white/50">
                  Local full sync uploads can also create missing profiles automatically.
                </p>
                <div className="flex space-x-3">
                  <button
                    onClick={() => addProfileMutation.mutate(newProfileUsername.trim())}
                    disabled={!newProfileUsername.trim() || addProfileMutation.isPending}
                    className="btn-primary flex-1 flex items-center justify-center space-x-2"
                  >
                    {addProfileMutation.isPending ? (
                      <ClockIcon className="w-4 h-4 animate-spin" />
                    ) : (
                      <PlusIcon className="w-4 h-4" />
                    )}
                    <span>Add Profile</span>
                  </button>
                  <button
                    onClick={() => {
                      setIsAddingProfile(false);
                      setNewProfileUsername('');
                    }}
                    className="btn-secondary"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      <motion.div
        className="space-y-6"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.5 }}
      >
        <AnimatePresence mode="popLayout">
          {filteredProfiles.length > 0 ? (
            <motion.div data-testid="tracked-profile-grid" className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6" layout>
              {filteredProfiles.map((profile) => {
                const badge = getStatusBadge(profile.scraping_status);
                const isPrimaryProfile = isPrimaryUsername(profile.username);
                const coverageSummary =
                  profile.data_coverage?.summary ||
                  'Run the local full sync workflow to populate this profile.';

                return (
                  <div key={profile.username} className="card-cinema relative" style={{ isolation: 'isolate' }}>
                    <div className="flex items-center justify-between mb-4">
                      <div className="flex items-center space-x-3">
                        <motion.div
                          className="w-12 h-12 bg-gradient-to-br from-cinema-400 to-cinema-600 rounded-full flex items-center justify-center shadow-glow"
                          whileHover={{ rotate: 360, scale: 1.1 }}
                          transition={{ duration: 0.6, ease: 'easeInOut' }}
                        >
                          <UserCircleIcon className="w-6 h-6 text-white" />
                        </motion.div>
                        <div>
                          <h3 className="text-lg font-bold text-white">@{profile.username}</h3>
                          <div className={`inline-flex items-center px-2 py-1 rounded-lg text-xs font-medium border ${badge.className}`}>
                            {badge.icon}
                            {badge.label}
                          </div>
                        </div>
                      </div>
                      {isAdmin ? (
                        <button
                          onClick={() => {
                            if (window.confirm(`Delete ${profile.username}? This cannot be undone.`)) {
                              deleteProfileMutation.mutate(profile.username);
                            }
                          }}
                          disabled={deletingProfile === profile.username}
                          className="p-3 rounded-lg bg-red-500/20 hover:bg-red-500/30 transition-colors disabled:opacity-50"
                          title="Delete profile"
                        >
                          <TrashIcon className={`w-4 h-4 text-red-400 ${deletingProfile === profile.username ? 'animate-pulse' : ''}`} />
                        </button>
                      ) : isPrimaryProfile ? (
                        <span
                          className="inline-flex items-center gap-2 rounded-lg border border-cinema-400/25 bg-cinema-500/10 px-3 py-2 text-xs font-semibold text-cinema-200"
                          title="Your Letterboxd profile is your Spyboxd identity"
                        >
                          <ShieldCheck className="h-4 w-4" />
                          Your profile
                        </span>
                      ) : (
                        <button
                          onClick={() => {
                            if (window.confirm(`Remove ${profile.username} from My Profiles? Shared profile data will not be deleted.`)) {
                              untrackProfileMutation.mutate(profile.username);
                            }
                          }}
                          disabled={untrackingProfile === profile.username}
                          className="rounded-lg border border-white/10 bg-white/5 p-3 transition-colors hover:border-red-400/25 hover:bg-red-500/10 disabled:opacity-50"
                          title="Remove from My Profiles"
                          aria-label={`Remove ${profile.username} from My Profiles`}
                        >
                          <TrashIcon className={`h-4 w-4 text-white/45 ${untrackingProfile === profile.username ? 'animate-pulse' : ''}`} />
                        </button>
                      )}
                    </div>

                    <div className="grid grid-cols-2 gap-3 mb-4">
                      <div className="text-center">
                        <div className="text-xl font-bold text-white">{profile.total_films?.toLocaleString() || '0'}</div>
                        <div className="text-xs text-white/60">Films</div>
                      </div>
                      <div className="text-center">
                        <div className="text-xl font-bold text-cinema-400">{profile.avg_rating?.toFixed(1) || '0.0'}</div>
                        <div className="text-xs text-white/60">Avg Rating</div>
                      </div>
                      <div className="text-center">
                        <div className="text-xl font-bold text-green-400">{profile.rated_films?.toLocaleString() || '0'}</div>
                        <div className="text-xs text-white/60">Rated</div>
                      </div>
                      <div className="text-center">
                        <div className="text-xl font-bold text-white">{profile.total_reviews?.toLocaleString() || '0'}</div>
                        <div className="text-xs text-white/60">Reviews</div>
                      </div>
                    </div>

                    <p className="text-xs text-white/50 text-center mb-3">{coverageSummary}</p>

                    {profile.last_scraped_at && (
                      <div className="text-xs text-white/50 text-center">
                        Synced {new Date(profile.last_scraped_at).toLocaleDateString()}
                      </div>
                    )}
                  </div>
                );
              })}
            </motion.div>
          ) : (
            <motion.div
              className="card-cinema text-center py-16"
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: 0.3 }}
            >
              <motion.div
                className="w-24 h-24 bg-cinema-500/20 rounded-full flex items-center justify-center mb-6 mx-auto"
                animate={{
                  scale: [1, 1.05, 1],
                  boxShadow: ['0 0 20px rgba(229,81,0,0.3)', '0 0 40px rgba(229,81,0,0.5)', '0 0 20px rgba(229,81,0,0.3)'],
                }}
                transition={{ duration: 2, repeat: Infinity }}
              >
                <Users className="w-12 h-12 text-cinema-400" />
              </motion.div>
              <h3 className="text-xl font-bold text-white mb-3">
                {searchTerm ? 'No profiles match your search' : isAdmin ? 'No managed profiles yet' : 'No tracked profiles yet'}
              </h3>
              <p className="text-white/60 mb-8 max-w-md mx-auto">
                {searchTerm
                  ? `No profiles found matching "${searchTerm}".`
                  : isAdmin
                    ? 'Add usernames here or let the residential sync workflow create them during upload.'
                    : 'Use Add or request above to start building the profile set used by your dashboard and comparisons.'}
              </p>
              {!searchTerm && isAdmin && (
                <motion.button
                  onClick={() => setIsAddingProfile(true)}
                  className="btn-primary flex items-center space-x-2 mx-auto"
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                >
                  <UserPlus className="w-5 h-5" />
                  <span>Add First Profile</span>
                </motion.button>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </motion.div>
  );
};

export default ProfileManager;
