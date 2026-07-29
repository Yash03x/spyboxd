'use client';

import React, { useEffect, useRef, useState } from 'react';
import { useUser } from '@clerk/nextjs';
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
import { FileArchive, ShieldCheck, Upload, UserPlus, Users } from 'lucide-react';
import { profileApi } from '../services/api';
import LoadingSpinner from '../components/LoadingSpinner';
import ErrorMessage from '../components/ErrorMessage';
import toast, { Toaster } from 'react-hot-toast';


const ProfileManager: React.FC = () => {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { user } = useUser();
  const isAdmin = Boolean(user?.publicMetadata?.is_admin);

  const [searchTerm, setSearchTerm] = useState('');
  const [isAddingProfile, setIsAddingProfile] = useState(false);
  const [newProfileUsername, setNewProfileUsername] = useState('');
  const [filterStatus, setFilterStatus] = useState<string>('all');
  const [deletingProfile, setDeletingProfile] = useState<string | null>(null);
  const [exportFiles, setExportFiles] = useState<FileList | null>(null);
  const [hasOwnerPublishingConsent, setHasOwnerPublishingConsent] = useState(false);
  const exportInputRef = useRef<HTMLInputElement>(null);

  const queryClient = useQueryClient();

  useEffect(() => {
    if (isAdmin && searchParams.get('add') === 'true') {
      setIsAddingProfile(true);
      router.replace('/profiles');
    }
  }, [isAdmin, searchParams, router]);

  const { data: profiles, isLoading, error } = useQuery({
    queryKey: ['profiles'],
    queryFn: profileApi.getProfiles,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const addProfileMutation = useMutation({
    mutationFn: profileApi.createProfile,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['profiles'] });
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
      queryClient.invalidateQueries({ queryKey: ['profiles'] });
      toast.success('Profile deleted successfully.');
      setDeletingProfile(null);
    },
    onError: (error: Error) => {
      toast.error(`Failed to delete profile: ${error.message}`);
      setDeletingProfile(null);
    },
  });

  const exportUploadMutation = useMutation({
    mutationFn: (files: FileList) => profileApi.uploadFiles(files, { publish_owner_data: true }),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ['profiles'] });
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

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorMessage message="Failed to load profiles" />;

  return (
    <motion.div
      className="space-y-8"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6 }}
    >
      <Toaster
        position="top-right"
        toastOptions={{
          className: 'bg-noir-800 text-white border border-cinema-400/20',
          duration: 4000,
        }}
      />

      <motion.div
        className="flex items-center justify-between"
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
      >
        <div>
          <h1 className="text-4xl font-bold text-white text-glow mb-2">Profiles</h1>
          <p className="text-white/60">
            {isAdmin
              ? 'Track usernames here, then sync full Letterboxd data from your residential machine.'
              : 'Browse the shared Letterboxd profile database.'}
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
            <span>Add Profile</span>
          </motion.button>
        )}
      </motion.div>

      <motion.div
        className="card-cinema"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
      >
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-2">
            <h2 className="text-xl font-bold text-white">Repeatable Sync Workflow</h2>
            <p className="text-sm text-white/70">
              {isAdmin
                ? 'VPS scraping is disabled. Full profile syncs now come only from the local residential runner.'
                : 'Profile updates are handled by admins through the local residential sync runner.'}
            </p>
          </div>
          <div className="rounded-xl bg-noir-900/60 border border-white/10 px-4 py-3 text-sm text-white/80 max-w-2xl">
            {isAdmin ? (
              <>
                <p>1. Add usernames here if you want placeholders in the UI.</p>
                <p>2. Create `sync-profiles.json` from `scripts/sync-profiles.example.json` on your local machine.</p>
                <p>3. Run `.venv/bin/python scripts/batch_full_sync.py --config sync-profiles.json`.</p>
                <p>4. Schedule that command with `launchd` or `cron`.</p>
              </>
            ) : (
              <>
                <p>This view is public.</p>
                <p>Admin-only sync operations run outside the browser and publish into this shared dataset.</p>
              </>
            )}
          </div>
        </div>
      </motion.div>

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
            <option value="all">All Profiles</option>
            <option value="synced">Synced</option>
            <option value="pending">Awaiting Sync</option>
            <option value="error">Error</option>
          </select>
        </div>
        <div className="text-white/60 text-sm">
          {filteredProfiles.length} of {profilesArray.length} profiles
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
            <motion.div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6" layout>
              {filteredProfiles.map((profile) => {
                const badge = getStatusBadge(profile.scraping_status);
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
                      {isAdmin && (
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
                {searchTerm ? 'No profiles match your search' : 'No profiles yet'}
              </h3>
              <p className="text-white/60 mb-8 max-w-md mx-auto">
                {searchTerm
                  ? `No profiles found matching "${searchTerm}".`
                  : 'Add usernames here or let the local sync workflow create them during upload.'}
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
