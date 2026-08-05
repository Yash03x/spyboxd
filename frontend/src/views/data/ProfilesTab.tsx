'use client';

import React, { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import { usePathname, useSearchParams } from 'next/navigation';

import Panel from '../../components/terminal/Panel';
import Notes from '../../components/terminal/bodies/Notes';
import Rows, { cell } from '../../components/terminal/bodies/Rows';
import { PanelSkeleton, panelState } from '../../components/terminal/states';
import { count } from '../../components/terminal/plural';
import { useAdminScope } from '../../hooks/useAdminScope';
import { useCurrentUser } from '../../hooks/useCurrentUser';
import {
  adminProfileRequestApi,
  dataHealthApi,
  followGraphApi,
  profileApi,
  type ProfileRequestStatus,
} from '../../services/api';

const REQUEST_STATE: Record<ProfileRequestStatus, { label: string; tone: string; next: string }> = {
  pending: {
    label: 'queued',
    tone: 'var(--ink3)',
    next: 'Waiting behind the refreshes already scheduled.',
  },
  approved: {
    label: 'accepted',
    tone: 'var(--accent)',
    next: 'Accepted — it will be read on the next full refresh.',
  },
  fulfilled: {
    label: 'done',
    tone: 'var(--ok)',
    next: 'Read and imported. It appears everywhere else in the product now.',
  },
  rejected: {
    label: 'blocked',
    tone: 'var(--bad)',
    next: 'Not readable — usually a private account, which no amount of retrying reaches.',
  },
};

/**
 * One sentence per identity state, keyed by what /api/me reports. The states
 * and their facts are the old profile manager's, restated in this voice.
 */
const IDENTITY_COPY: Record<string, string> = {
  tracked: 'Synced, and part of your monitored set.',
  pending: 'Requested automatically. It is awaiting review before a residential full sync.',
  approved: 'Approved, and queued for the next residential full sync.',
  rejected: 'The request was not approved. If the username is right, ask the administrator.',
  available: 'Already synced here — monitor it from the chooser below.',
  unlinked: 'Linked to this login, but its profile has not been requested yet.',
  unconfigured:
    'No Letterboxd username is linked to this login. Ask the administrator to repair the identity.',
};

const CATALOG_RESULT_LIMIT = 100;
const CATALOG_SEARCH_DELAY_MS = 250;

function relative(iso: string | null | undefined): string {
  if (!iso) return 'never';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return 'never';
  const hours = Math.round((Date.now() - then) / 36e5);
  if (hours < 1) return 'just now';
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function duration(seconds: number | null): string {
  if (seconds === null) return '—';
  if (seconds < 90) return `${Math.round(seconds)}s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `${minutes}m`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

function errorText(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error ?? 'unknown error');
}

interface Outcome {
  ok: boolean;
  text: string;
}

/** The one button style on this tab: mono, bordered, honest about being busy. */
function ActionButton({
  label,
  busyLabel = 'SAVING…',
  busy = false,
  disabled = false,
  tone = 'var(--ink3)',
  onClick,
  ariaLabel,
  ariaExpanded,
}: {
  label: string;
  busyLabel?: string;
  busy?: boolean;
  disabled?: boolean;
  tone?: string;
  onClick: () => void;
  ariaLabel?: string;
  ariaExpanded?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || busy}
      aria-label={ariaLabel ?? label}
      aria-expanded={ariaExpanded}
      className="rounded-[3px] border border-term-rule bg-transparent px-[7px] py-[2px] text-t9 font-bold tracking-tab hover:border-term-accent hover:text-term-accent disabled:cursor-not-allowed disabled:opacity-40"
      style={{ color: tone }}
    >
      {busy ? busyLabel : label}
    </button>
  );
}

/**
 * Arm-and-confirm without a dialog. The arming control is the SAME element in
 * both states, so keyboard focus survives the swap; only the escape hatch
 * mounts and unmounts beside it.
 */
function ArmedAction({
  label,
  confirmLabel,
  busyLabel,
  ariaLabelIdle,
  ariaLabelArmed,
  armed,
  busy,
  tone = 'var(--bad)',
  onArm,
  onConfirm,
  onDisarm,
  subject,
}: {
  label: string;
  confirmLabel: string;
  busyLabel: string;
  ariaLabelIdle: string;
  ariaLabelArmed: string;
  armed: boolean;
  busy: boolean;
  tone?: string;
  onArm: () => void;
  onConfirm: () => void;
  onDisarm: () => void;
  subject: string;
}) {
  return (
    <>
      <ActionButton
        label={armed ? confirmLabel : label}
        busyLabel={busyLabel}
        busy={busy}
        tone={tone}
        onClick={armed ? onConfirm : onArm}
        ariaLabel={armed ? ariaLabelArmed : ariaLabelIdle}
        ariaExpanded={armed}
      />
      {armed ? (
        <ActionButton
          label="KEEP"
          busy={false}
          disabled={busy}
          onClick={onDisarm}
          ariaLabel={`Keep ${subject}`}
        />
      ) : null}
    </>
  );
}

/**
 * Inline outcome line for a mutation: the panel's own toast replacement. The
 * live region is always mounted so screen readers announce content changes;
 * it collapses visually while empty.
 */
function OutcomeLine({ outcome }: { outcome: Outcome | null }) {
  return (
    <p
      role="status"
      aria-live="polite"
      className={
        outcome
          ? 'm-0 border-t border-term-rule2 px-[10px] py-[6px] font-term-sans text-t10'
          : 'm-0 h-0 overflow-hidden'
      }
      style={outcome ? { color: outcome.ok ? 'var(--ok)' : 'var(--bad)' } : undefined}
    >
      {outcome ? outcome.text : ''}
    </p>
  );
}

const inputClass =
  'w-full rounded-[3px] border border-term-rule bg-transparent px-[8px] py-[5px] font-term-sans text-t11 text-term-ink placeholder:text-term-dim focus:border-term-accent focus:outline-none';

const LIBRARY_STATES = ['all', 'synced', 'pending', 'error'] as const;
type LibraryState = (typeof LIBRARY_STATES)[number];

function matchesLibraryState(status: string | undefined, state: LibraryState): boolean {
  if (state === 'all') return true;
  if (state === 'synced') return status === 'completed';
  if (state === 'error') return status === 'error';
  // "Awaiting sync" is everything not yet read AND not failed -- the three
  // chips must partition the library, or a filtered count double-counts.
  return status !== 'completed' && status !== 'error';
}

export default function ProfilesTab({
  profiles,
  selectionLoading = false,
}: {
  profiles: string[];
  selectionLoading?: boolean;
}) {
  const { isAdmin, userReady } = useAdminScope();
  const currentUserQuery = useCurrentUser();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const isOnboarding = searchParams.get('onboarding') === '1';
  const wantsPlaceholderFocus = searchParams.get('add') === 'true';
  const rawLibraryState = searchParams.get('state');
  const libraryState: LibraryState = (LIBRARY_STATES as readonly string[]).includes(
    rawLibraryState ?? '',
  )
    ? (rawLibraryState as LibraryState)
    : 'all';
  const queryClient = useQueryClient();
  const enabled = profiles.length > 0;

  const libraryStateHref = (state: LibraryState) => {
    const params = new URLSearchParams(searchParams.toString());
    if (state === 'all') params.delete('state');
    else params.set('state', state);
    const query = params.toString();
    return query ? `${pathname}?${query}` : pathname;
  };

  const [catalogSearch, setCatalogSearch] = useState('');
  const [debouncedCatalogSearch, setDebouncedCatalogSearch] = useState('');
  const [librarySearch, setLibrarySearch] = useState('');
  const [requestedUsername, setRequestedUsername] = useState('');
  const [askBusy, setAskBusy] = useState(false);
  const [requestOutcome, setRequestOutcome] = useState<Outcome | null>(null);
  const [catalogOutcome, setCatalogOutcome] = useState<Outcome | null>(null);
  const [libraryOutcome, setLibraryOutcome] = useState<Outcome | null>(null);
  const [suggestionOutcome, setSuggestionOutcome] = useState<Outcome | null>(null);
  const [queueOutcome, setQueueOutcome] = useState<Outcome | null>(null);
  const [placeholderOutcome, setPlaceholderOutcome] = useState<Outcome | null>(null);
  const [residentialOutcome, setResidentialOutcome] = useState<Outcome | null>(null);
  const [exportOutcome, setExportOutcome] = useState<Outcome | null>(null);
  // Sets, not scalars: two in-flight mutations must not clear each other's
  // busy state when the first one settles.
  const [busyProfileIds, setBusyProfileIds] = useState<ReadonlySet<number>>(new Set());
  const [busyUsernames, setBusyUsernames] = useState<ReadonlySet<string>>(new Set());
  const [busyRequestId, setBusyRequestId] = useState<number | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null);
  const [confirmingUntrack, setConfirmingUntrack] = useState<string | null>(null);
  const [adminNotes, setAdminNotes] = useState<Record<number, string>>({});
  const [placeholderUsername, setPlaceholderUsername] = useState('');
  const [residentialFiles, setResidentialFiles] = useState<FileList | null>(null);
  const [exportFiles, setExportFiles] = useState<FileList | null>(null);
  const [hasOwnerConsent, setHasOwnerConsent] = useState(false);
  const residentialInputRef = useRef<HTMLInputElement>(null);
  const exportInputRef = useRef<HTMLInputElement>(null);
  const placeholderInputRef = useRef<HTMLInputElement>(null);

  const addBusyProfile = (id: number) =>
    setBusyProfileIds((prev) => new Set(prev).add(id));
  const removeBusyProfile = (id: number) =>
    setBusyProfileIds((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  const addBusyUsername = (username: string) =>
    setBusyUsernames((prev) => new Set(prev).add(username));
  const removeBusyUsername = (username: string) =>
    setBusyUsernames((prev) => {
      const next = new Set(prev);
      next.delete(username);
      return next;
    });

  useEffect(() => {
    const timeout = window.setTimeout(
      () => setDebouncedCatalogSearch(catalogSearch.trim()),
      CATALOG_SEARCH_DELAY_MS,
    );
    return () => window.clearTimeout(timeout);
  }, [catalogSearch]);

  // ?add=true deep-links the admin straight into the placeholder form. The
  // panel mounts late (after /api/me resolves), so this must not yank focus
  // away from anything the reader has since started using.
  useEffect(() => {
    if (!wantsPlaceholderFocus || !isAdmin) return;
    const input = placeholderInputRef.current;
    if (input && document.activeElement === document.body) input.focus();
  }, [wantsPlaceholderFocus, isAdmin]);

  const freshnessQuery = useQuery({
    queryKey: ['data-freshness', profiles],
    queryFn: () => dataHealthApi.getFreshness(profiles),
    enabled,
    staleTime: 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const catalogQuery = useQuery({
    queryKey: ['profile-catalog', debouncedCatalogSearch],
    queryFn: () => profileApi.getCatalog(debouncedCatalogSearch, CATALOG_RESULT_LIMIT),
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    // A refetch (new search term, or an invalidation after a mutation) keeps
    // the current rows on screen rather than unmounting the list to a
    // skeleton under the reader's cursor.
    placeholderData: keepPreviousData,
  });

  const libraryQuery = useQuery({
    queryKey: ['profiles'],
    queryFn: profileApi.getProfiles,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  // The caller's personal monitoring set, for both roles: for a non-admin the
  // library above IS that set, but for an admin it is the whole managed
  // library, and counting it would report the library's size as "monitored".
  const trackedQuery = useQuery({
    queryKey: ['profiles', 'tracked', 'data-profiles'],
    queryFn: profileApi.getTrackedProfiles,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const requestsQuery = useQuery({
    queryKey: ['profile-requests'],
    queryFn: () => profileApi.getRequests(),
    staleTime: 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const suggestionsQuery = useQuery({
    queryKey: ['follow-suggestions', 'data'],
    queryFn: () => followGraphApi.getSuggestions({ limit: 20, minOverlap: 2 }),
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const latencyQuery = useQuery({
    queryKey: ['data-latency', profiles],
    queryFn: () => dataHealthApi.getRequestLatency(profiles),
    enabled,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const adminQueueQuery = useQuery({
    queryKey: ['admin-profile-requests'],
    queryFn: () => adminProfileRequestApi.getRequests(),
    enabled: userReady && isAdmin,
    staleTime: 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const refreshProfileSurfaces = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ['profiles'] }),
      queryClient.invalidateQueries({ queryKey: ['profile-catalog'] }),
      queryClient.invalidateQueries({ queryKey: ['profile-requests'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-profile-requests'] }),
      queryClient.invalidateQueries({ queryKey: ['data-freshness'] }),
      queryClient.invalidateQueries({ queryKey: ['data-latency'] }),
      queryClient.invalidateQueries({ queryKey: ['dashboard-analytics'] }),
      queryClient.invalidateQueries({ queryKey: ['recent-changes'] }),
      queryClient.invalidateQueries({ queryKey: ['follow-suggestions'] }),
      queryClient.invalidateQueries({ queryKey: ['follow-graph'] }),
      queryClient.invalidateQueries({ queryKey: ['current-user'] }),
    ]);

  // Mutation configs hold only what is true for EVERY caller (the surface
  // refresh and busy bookkeeping). Outcome lines and input clearing belong to
  // the panel that initiated the call, and live in per-call callbacks --
  // config-level versions fired for other panels' calls too, wiping the ask
  // form mid-typing and writing outcome lines under the wrong panel.
  const requestMutation = useMutation({
    mutationFn: (username: string) => profileApi.requestProfile(username),
    onSuccess: () => void refreshProfileSurfaces(),
    onMutate: (username) => addBusyUsername(username),
    onSettled: (_data, _error, username) => removeBusyUsername(username),
  });

  const trackMutation = useMutation({
    mutationFn: (profileId: number) => profileApi.trackExisting(profileId),
    onSuccess: () => void refreshProfileSurfaces(),
    onMutate: (profileId) => addBusyProfile(profileId),
    onSettled: (_data, _error, profileId) => removeBusyProfile(profileId),
  });

  const untrackMutation = useMutation({
    mutationFn: (username: string) => profileApi.stopTracking(username),
    onSuccess: () => void refreshProfileSurfaces(),
    onMutate: (username) => addBusyUsername(username),
    onSettled: (_data, _error, username) => {
      removeBusyUsername(username);
      setConfirmingUntrack((current) => (current === username ? null : current));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (username: string) => profileApi.deleteProfile(username),
    onSuccess: () => void refreshProfileSurfaces(),
    onMutate: (username) => addBusyUsername(username),
    onSettled: (_data, _error, username) => {
      removeBusyUsername(username);
      setConfirmingDelete((current) => (current === username ? null : current));
    },
  });

  const reviewMutation = useMutation({
    mutationFn: ({ id, status }: { id: number; status: 'approved' | 'rejected' }) =>
      adminProfileRequestApi.updateRequest(id, status, adminNotes[id]?.trim() || undefined),
    onMutate: ({ id }) => setBusyRequestId(id),
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
      setQueueOutcome({
        ok: true,
        text:
          result.request.status === 'rejected'
            ? `@${result.request.requested_username} was rejected.`
            : `@${result.request.requested_username} was accepted for the next residential sync.`,
      });
    },
    onError: (error: Error) =>
      setQueueOutcome({ ok: false, text: `The decision failed: ${errorText(error)}` }),
    onSettled: () => setBusyRequestId(null),
  });

  const placeholderMutation = useMutation({
    mutationFn: profileApi.createProfile,
    onSuccess: (_result, username) => {
      void refreshProfileSurfaces();
      setPlaceholderUsername('');
      setPlaceholderOutcome({
        ok: true,
        text: `@${username} exists as a placeholder. A residential upload fills it.`,
      });
    },
    onError: (error: Error) =>
      setPlaceholderOutcome({ ok: false, text: `Placeholder failed: ${errorText(error)}` }),
  });

  const uploadSummary = (result: Awaited<ReturnType<typeof profileApi.uploadFiles>>) => {
    const loaded = result.loaded_profiles.length;
    const kinds = Array.from(new Set((result.imports ?? []).map((item) => item.source_kind)));
    const provenance = kinds.length > 0 ? ` Provenance: ${kinds.join(', ')}.` : '';
    const errors = result.errors?.length ? ` Errors: ${result.errors.join(' ')}` : '';
    return { loaded, text: `${count(loaded, 'bundle')} imported.${provenance}${errors}` };
  };

  const residentialMutation = useMutation({
    mutationFn: (files: FileList) =>
      profileApi.uploadFiles(files, { publish_owner_data: false, require_full_sync: true }),
    onSuccess: (result) => {
      void refreshProfileSurfaces();
      const summary = uploadSummary(result);
      setResidentialOutcome({ ok: (result.errors?.length ?? 0) === 0, text: summary.text });
      setResidentialFiles(null);
      if (residentialInputRef.current) residentialInputRef.current.value = '';
    },
    onError: (error: Error) =>
      setResidentialOutcome({ ok: false, text: `The upload failed: ${errorText(error)}` }),
  });

  const exportMutation = useMutation({
    mutationFn: (files: FileList) => profileApi.uploadFiles(files, { publish_owner_data: true }),
    onSuccess: (result) => {
      void refreshProfileSurfaces();
      const summary = uploadSummary(result);
      setExportOutcome({ ok: (result.errors?.length ?? 0) === 0, text: summary.text });
      setExportFiles(null);
      setHasOwnerConsent(false);
      if (exportInputRef.current) exportInputRef.current.value = '';
    },
    onError: (error: Error) =>
      setExportOutcome({ ok: false, text: `The import failed: ${errorText(error)}` }),
  });

  const submitRequest = (username: string, setOutcome: (outcome: Outcome) => void) =>
    requestMutation.mutate(username, {
      onSuccess: (result) =>
        setOutcome({
          ok: true,
          text:
            result.status === 'tracked'
              ? `@${username} was already synced — added straight to your monitored set.`
              : `@${username} was requested. Its state appears in YOUR REQUEST STATUS.`,
        }),
      onError: (error: Error) =>
        setOutcome({ ok: false, text: `The request failed: ${errorText(error)}` }),
    });

  const submitTrack = (
    profileId: number,
    username: string,
    setOutcome: (outcome: Outcome) => void,
  ) =>
    trackMutation.mutate(profileId, {
      onSuccess: () => setOutcome({ ok: true, text: `@${username} is now monitored.` }),
      onError: (error: Error) =>
        setOutcome({ ok: false, text: `Monitoring failed: ${errorText(error)}` }),
    });

  const submitUntrack = (username: string, setOutcome: (outcome: Outcome) => void) =>
    untrackMutation.mutate(username, {
      onSuccess: () =>
        setOutcome({
          ok: true,
          text: `@${username} is no longer monitored. Its imported history stays.`,
        }),
      onError: (error: Error) =>
        setOutcome({ ok: false, text: `Unmonitoring failed: ${errorText(error)}` }),
    });

  const submitDelete = (username: string, setOutcome: (outcome: Outcome) => void) =>
    deleteMutation.mutate(username, {
      onSuccess: () =>
        setOutcome({ ok: true, text: `@${username} was deleted from the library.` }),
      onError: (error: Error) =>
        setOutcome({ ok: false, text: `Deletion failed: ${errorText(error)}` }),
    });

  const me = currentUserQuery.data;
  const primaryUsername = me?.letterboxd_username ?? null;
  const primaryStatus = me?.primary_profile_status ?? 'unconfigured';
  const isPrimaryUsername = (username: string) =>
    primaryUsername !== null && username.toLowerCase() === primaryUsername.toLowerCase();

  const catalogProfiles = catalogQuery.data?.profiles ?? [];
  const catalogTotal = catalogQuery.data?.total ?? 0;
  const catalogLimit = catalogQuery.data?.limit ?? CATALOG_RESULT_LIMIT;
  const isSearchPending =
    catalogSearch.trim() !== debouncedCatalogSearch || catalogQuery.isFetching;
  const normalizedRequest = requestedUsername.trim().replace(/^@/, '');
  const libraryProfiles = libraryQuery.data ?? [];
  const normalizedLibrarySearch = librarySearch.trim().toLowerCase();
  const filteredLibrary = libraryProfiles.filter(
    (profile) =>
      matchesLibraryState(profile.scraping_status, libraryState) &&
      (normalizedLibrarySearch === '' ||
        profile.username.toLowerCase().includes(normalizedLibrarySearch)),
  );

  return (
    <>
      <Panel
        title="WHO THIS LOGIN IS"
        src="app_users · /api/me"
        blurb={
          isOnboarding
            ? 'Welcome. This is the Letterboxd identity attached to the account you just created, and the state it starts in.'
            : undefined
        }
        caveat="Your monitoring choices are private to this login. They decide what the rest of the product shows you, and nothing else sees them."
      >
        {panelState({
          isLoading: currentUserQuery.isLoading,
          error: currentUserQuery.error,
          isEmpty: false,
          severity: 'degraded',
          onRetry: () => currentUserQuery.refetch(),
          errorTitle: 'Your identity could not be loaded',
          errorBody: 'Every other panel on this tab still works.',
          skeleton: <PanelSkeleton rows={2} />,
        }) ?? (
          <div className="px-[10px] py-[10px]" data-testid="primary-profile-status">
            <p className="m-0 terminal-num text-t14 font-bold text-term-ink">
              {primaryUsername ? `@${primaryUsername}` : 'no username linked'}
            </p>
            <p className="m-0 mt-[5px] max-w-[42rem] font-term-sans text-t105 text-term-ink3">
              {IDENTITY_COPY[primaryStatus] ?? IDENTITY_COPY.unconfigured}
            </p>
          </div>
        )}
      </Panel>

      <Panel
        title="EVERYONE WE HAVE SYNCED"
        src="profiles · profile_syncs"
        wide
        blurb="Each row links to People › The circle, centred on that profile — the follow lists and the graph live there."
        caveat={freshnessQuery.data?.caveat}
      >
        {panelState({
          // A disabled query reports "not loading", but an unresolved
          // selection is not an empty roster -- claiming "nobody synced" while
          // the profile list is still on the wire would be a false statement.
          isLoading: freshnessQuery.isLoading || (selectionLoading && !enabled),
          error: freshnessQuery.error,
          isEmpty: (freshnessQuery.data?.profiles.length ?? 0) === 0,
          severity: 'fatal',
          onRetry: () => freshnessQuery.refetch(),
          errorTitle: 'Available profiles could not be loaded',
          errorBody: 'You can still request a username by hand while this is down.',
          empty: {
            title: 'Nobody synced here yet',
            body: 'Ask for a username below and it will be read on the next full refresh.',
          },
        }) ?? (
          <Rows
            columns="minmax(0,1fr) 90px 90px minmax(0,1fr)"
            // "THEY REPORT", because the figure is Letterboxd's own header
            // count, not our imported rows — for a freshly synced profile the
            // two differ, and a column named FILMS HELD showing the number we
            // do NOT hold inverted the fact. Our count is the roster's FILMS
            // column on Overview, and the gap between the two is the whole
            // subject of Data › What's missing.
            head={['PROFILE', ['WATCHES', 'right'], ['LAST READ', 'right'], 'THEY REPORT']}
            rows={(freshnessQuery.data?.profiles ?? []).map((entry) => {
              return {
                href: `/people?tab=circle&subject=${encodeURIComponent(entry.username)}`,
                cells: [
                  cell(`@${entry.username}`),
                  cell(entry.watch_events.toLocaleString(), {
                    align: 'right',
                    tone: 'var(--ink)',
                  }),
                  cell(relative(entry.last_read_at), {
                    align: 'right',
                    size: '10px',
                    tone:
                      entry.hours_ago === null
                        ? 'var(--dim)'
                        : entry.hours_ago > 24 * 7
                          ? 'var(--bad)'
                          : entry.hours_ago > 24
                            ? 'var(--accent)'
                            : 'var(--ok)',
                  }),
                  // A header nobody has read holds no number. This used to
                  // read the tracked-profile list, which does not cover every
                  // profile on screen, and rendered a confident 0 for the ones
                  // it missed — beside their own non-zero watch count.
                  cell(
                    entry.films_held === null ? 'never read' : entry.films_held.toLocaleString(),
                    {
                      align: 'right',
                      size: '10px',
                      tone: entry.films_held === null ? 'var(--dim)' : 'var(--muted)',
                    },
                  ),
                ],
              };
            })}
          />
        )}
      </Panel>

      <Panel
        title="THE LIBRARY'S STATE"
        src="profiles · scraping_status · data_coverage"
        wide
        blurb="Every profile this instance manages, with what its last read achieved. The roster above is freshness; this is depth."
      >
        <div className="flex flex-wrap items-center gap-[6px] border-b border-term-rule2 px-[10px] py-[5px]">
          {LIBRARY_STATES.map((state) => (
            <Link
              key={state}
              href={libraryStateHref(state)}
              aria-current={libraryState === state ? 'true' : undefined}
              className={`rounded-[3px] border px-[7px] py-[2px] text-t9 font-bold uppercase tracking-tab no-underline hover:no-underline ${
                libraryState === state
                  ? 'border-term-accent text-term-accent'
                  : 'border-term-rule text-term-ink3 hover:border-term-accent hover:text-term-accent'
              }`}
            >
              {state === 'pending' ? 'awaiting sync' : state}
            </Link>
          ))}
          <label className="min-w-[140px] flex-1">
            <span className="sr-only">Search the library</span>
            <input
              type="search"
              value={librarySearch}
              onChange={(event) => setLibrarySearch(event.target.value)}
              placeholder="Search the library…"
              className={inputClass}
            />
          </label>
          <span className="ml-auto font-term-sans text-t10 text-term-dim">
            {libraryQuery.data
              ? `${filteredLibrary.length.toLocaleString()} of ${count(libraryProfiles.length, isAdmin ? 'managed profile' : 'tracked profile')}`
              : ''}
          </span>
        </div>
        {panelState({
          isLoading: libraryQuery.isLoading,
          error: libraryQuery.error,
          isEmpty: filteredLibrary.length === 0,
          severity: 'degraded',
          onRetry: () => libraryQuery.refetch(),
          errorTitle: 'The library could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty:
            libraryProfiles.length > 0
              ? {
                  title: normalizedLibrarySearch
                    ? 'No library profile matches that search'
                    : `Nothing in the "${libraryState === 'pending' ? 'awaiting sync' : libraryState}" state`,
                  body: `All ${count(libraryProfiles.length, 'profile')} sit outside this view — the filter hid them, it did not lose them.`,
                }
              : {
                  title: isAdmin ? 'No managed profiles yet' : 'No tracked profiles yet',
                  body: isAdmin
                    ? 'Add a placeholder below, or let a residential upload create profiles during import.'
                    : 'Use ASK FOR SOMEONE NEW below to start building the set your product reads.',
                },
        }) ?? (
          // Nine columns cannot compress into a phone viewport; the table
          // keeps its geometry and scrolls sideways instead of overflowing
          // into the neighbouring panels.
          <div className="overflow-x-auto">
            <div className="min-w-[880px]">
          <Rows
            columns="minmax(0,1.1fr) 58px 58px 48px 62px 78px 92px minmax(0,1.2fr) 118px"
            head={[
              'PROFILE',
              ['FILMS', 'right'],
              ['RATED', 'right'],
              ['AVG', 'right'],
              ['REVIEWS', 'right'],
              ['SYNCED', 'right'],
              ['STATE', 'right'],
              'COVERAGE',
              ['ACTION', 'right'],
            ]}
            rows={filteredLibrary.map((profile) => {
              const busy = busyUsernames.has(profile.username);
              const primary = isPrimaryUsername(profile.username);
              return {
                cells: [
                  cell(`@${profile.username}`, { tone: 'var(--ink)' }),
                  cell(profile.total_films?.toLocaleString() ?? '—', { align: 'right' }),
                  cell(profile.rated_films?.toLocaleString() ?? '—', { align: 'right' }),
                  // A profile with no ratings has no average, not an average
                  // of zero.
                  cell(profile.rated_films ? profile.avg_rating.toFixed(1) : '—', {
                    align: 'right',
                    tone: profile.rated_films ? 'var(--accent)' : 'var(--dim)',
                  }),
                  cell(profile.total_reviews?.toLocaleString() ?? '—', { align: 'right' }),
                  cell(
                    profile.last_scraped_at
                      ? new Date(profile.last_scraped_at).toLocaleDateString()
                      : 'no date',
                    {
                      align: 'right',
                      size: '10px',
                      tone: profile.last_scraped_at ? 'var(--muted)' : 'var(--dim)',
                    },
                  ),
                  cell(
                    profile.scraping_status === 'completed'
                      ? 'full sync'
                      : profile.scraping_status === 'error'
                        ? 'error'
                        : 'awaiting sync',
                    {
                      align: 'right',
                      size: '10px',
                      tone:
                        profile.scraping_status === 'completed'
                          ? 'var(--ok)'
                          : profile.scraping_status === 'error'
                            ? 'var(--bad)'
                            : 'var(--accent)',
                    },
                  ),
                  cell(
                    profile.data_coverage?.summary ||
                      'Run the local full sync workflow to populate this profile.',
                    { font: 's', size: '10px', tone: 'var(--dim)', wrap: true },
                  ),
                  // The library carries actions the catalog cannot: it lists
                  // profiles the catalog hides (errored, placeholders, and --
                  // for a non-admin -- anything tracked from outside their
                  // follow corner), and without this column those rows had no
                  // way to be untracked or deleted at all.
                  cell(
                    <span className="flex items-center justify-end gap-[5px]">
                      {isAdmin ? (
                        <ArmedAction
                          label="DELETE"
                          confirmLabel="SURE?"
                          busyLabel="DELETING…"
                          ariaLabelIdle={`Delete profile ${profile.username}`}
                          ariaLabelArmed={`Confirm deleting ${profile.username}`}
                          armed={confirmingDelete === profile.username}
                          busy={busy && deleteMutation.isPending}
                          onArm={() => setConfirmingDelete(profile.username)}
                          onConfirm={() => submitDelete(profile.username, setLibraryOutcome)}
                          onDisarm={() => setConfirmingDelete(null)}
                          subject={profile.username}
                        />
                      ) : primary ? (
                        <span className="text-t9 text-term-dim">yours to keep</span>
                      ) : (
                        <ArmedAction
                          label="STOP"
                          confirmLabel="SURE?"
                          busyLabel="SAVING…"
                          ariaLabelIdle={`Stop monitoring ${profile.username} from the library`}
                          ariaLabelArmed={`Confirm stop monitoring ${profile.username}`}
                          armed={confirmingUntrack === profile.username}
                          busy={busy && untrackMutation.isPending}
                          onArm={() => setConfirmingUntrack(profile.username)}
                          onConfirm={() => submitUntrack(profile.username, setLibraryOutcome)}
                          onDisarm={() => setConfirmingUntrack(null)}
                          subject={profile.username}
                        />
                      )}
                    </span>,
                    { align: 'right' },
                  ),
                ],
              };
            })}
          />
            </div>
          </div>
        )}
        <OutcomeLine outcome={libraryOutcome} />
      </Panel>

      <Panel
        title="CHOOSE WHO YOU MONITOR"
        src="profiles/catalog · user_tracked_profiles"
        wide
        stats={
          trackedQuery.data
            ? [{ big: trackedQuery.data.length, unit: 'MONITORED', tone: 'var(--accent)' }]
            : undefined
        }
        caveat="Stop monitoring somebody and their history stays. The store is append-only, so unmonitoring hides a profile from your product without deleting anything."
      >
        <div className="border-b border-term-rule2 px-[10px] py-[7px]">
          <label className="block">
            <span className="sr-only">Search available profiles</span>
            <input
              type="search"
              value={catalogSearch}
              onChange={(event) => setCatalogSearch(event.target.value)}
              placeholder="Search available profiles…"
              className={inputClass}
            />
          </label>
        </div>
        {panelState({
          isLoading: catalogQuery.isLoading,
          error: catalogQuery.error,
          isEmpty: catalogProfiles.length === 0 && !isSearchPending,
          severity: 'degraded',
          onRetry: () => catalogQuery.refetch(),
          errorTitle: 'Available profiles could not be loaded',
          errorBody: 'You can still request a username by hand below.',
          empty: {
            title: debouncedCatalogSearch
              ? 'No synced profiles match that search'
              : 'No synced profiles are available yet',
            body: debouncedCatalogSearch
              ? 'The search runs over every synced profile, so a miss means the name is not here yet. Ask for it below.'
              : 'Ask for a username below and it will be read on the next full refresh.',
          },
        }) ?? (
          <>
            <p
              className="m-0 border-b border-term-rule2 px-[10px] py-[5px] font-term-sans text-t10 text-term-dim"
              data-testid="profile-catalog-result-summary"
            >
              {isSearchPending ? 'Searching… · ' : ''}
              {catalogProfiles.length === catalogTotal
                ? `${count(catalogTotal, `${debouncedCatalogSearch ? 'matching ' : ''}synced profile`)}`
                : `Showing ${catalogProfiles.length.toLocaleString()} of ${catalogTotal.toLocaleString()} ${debouncedCatalogSearch ? 'matching ' : ''}synced profiles — results stop at ${catalogLimit.toLocaleString()} per search; refine the search to reach the rest.`}
            </p>
            <Rows
              columns={
                isAdmin
                  ? 'minmax(0,1fr) 70px 110px 170px'
                  : 'minmax(0,1fr) 70px 110px 110px'
              }
              head={['PROFILE', ['FILMS', 'right'], ['STATE', 'right'], ['ACTION', 'right']]}
              rows={catalogProfiles.map((profile) => {
                const busy =
                  busyProfileIds.has(profile.id) || busyUsernames.has(profile.username);
                const primary = isPrimaryUsername(profile.username);
                return {
                  cells: [
                    cell(
                      profile.display_name
                        ? `@${profile.username} · ${profile.display_name}`
                        : `@${profile.username}`,
                      { tone: 'var(--ink)' },
                    ),
                    cell(profile.total_films.toLocaleString(), { align: 'right' }),
                    cell(
                      primary && profile.is_tracked
                        ? 'your profile'
                        : profile.is_tracked
                          ? 'monitored'
                          : 'not monitored',
                      {
                        align: 'right',
                        size: '10px',
                        tone:
                          primary && profile.is_tracked
                            ? 'var(--accent)'
                            : profile.is_tracked
                              ? 'var(--ok)'
                              : 'var(--dim)',
                      },
                    ),
                    cell(
                      <span className="flex items-center justify-end gap-[5px]">
                        {primary && profile.is_tracked ? (
                          <span className="text-t9 text-term-dim">yours to keep</span>
                        ) : (
                          <ActionButton
                            label={profile.is_tracked ? 'STOP' : 'MONITOR'}
                            busy={busy && (trackMutation.isPending || untrackMutation.isPending)}
                            onClick={() =>
                              profile.is_tracked
                                ? submitUntrack(profile.username, setCatalogOutcome)
                                : submitTrack(profile.id, profile.username, setCatalogOutcome)
                            }
                            ariaLabel={`${profile.is_tracked ? 'Stop monitoring' : 'Monitor'} ${profile.username}`}
                          />
                        )}
                        {isAdmin ? (
                          <ArmedAction
                            label="DELETE"
                            confirmLabel="SURE?"
                            busyLabel="DELETING…"
                            ariaLabelIdle={`Delete profile ${profile.username}`}
                            ariaLabelArmed={`Confirm deleting ${profile.username}`}
                            armed={confirmingDelete === profile.username}
                            busy={busy && deleteMutation.isPending}
                            onArm={() => setConfirmingDelete(profile.username)}
                            onConfirm={() => submitDelete(profile.username, setCatalogOutcome)}
                            onDisarm={() => setConfirmingDelete(null)}
                            subject={profile.username}
                          />
                        ) : null}
                      </span>,
                      { align: 'right' },
                    ),
                  ],
                };
              })}
            />
          </>
        )}
        <OutcomeLine outcome={catalogOutcome} />
      </Panel>

      <Panel
        title="ASK FOR SOMEONE NEW"
        src="profile_access_requests"
        blurb="A username Spyboxd does not hold yet. It goes to review, and once accepted it is read on the next residential full refresh."
        caveat="A first import is a baseline: change-detection panels stay empty until the second refresh. An owner export unlocks likes, comments, pronouns and deleted history that public pages never show."
      >
        <form
          className="flex items-center gap-[7px] px-[10px] py-[9px]"
          onSubmit={(event) => {
            event.preventDefault();
            if (!normalizedRequest || askBusy) return;
            setAskBusy(true);
            requestMutation.mutate(normalizedRequest, {
              onSuccess: (result) => {
                setRequestedUsername('');
                setRequestOutcome({
                  ok: true,
                  text:
                    result.status === 'tracked'
                      ? `@${normalizedRequest} was already synced — added straight to your monitored set.`
                      : `@${normalizedRequest} was requested. Its state appears in YOUR REQUEST STATUS below.`,
                });
              },
              onError: (error: Error) =>
                setRequestOutcome({ ok: false, text: `The request failed: ${errorText(error)}` }),
              onSettled: () => setAskBusy(false),
            });
          }}
        >
          <label className="min-w-0 flex-1">
            <span className="sr-only">Letterboxd username</span>
            <input
              type="text"
              value={requestedUsername}
              onChange={(event) => setRequestedUsername(event.target.value)}
              placeholder="Letterboxd username"
              autoComplete="off"
              maxLength={16}
              pattern="@?[A-Za-z0-9_]{2,15}"
              title="Use 2–15 letters, numbers, or underscores."
              className={inputClass}
            />
          </label>
          <button
            type="submit"
            disabled={!normalizedRequest || askBusy}
            className="shrink-0 rounded-[3px] border border-term-rule bg-transparent px-[9px] py-[5px] text-t95 font-bold tracking-tab text-term-ink3 hover:border-term-accent hover:text-term-accent disabled:cursor-not-allowed disabled:opacity-40"
          >
            {askBusy ? 'SUBMITTING…' : 'ADD OR REQUEST'}
          </button>
        </form>
        <OutcomeLine outcome={requestOutcome} />
      </Panel>

      <Panel
        title="WHO TO TRACK NEXT"
        src="profile_follow_edges × profiles absence"
        blurb="Ranked by how many of the group already follow them. Same computation as the orbit panel in People, surfaced where you can act on it."
        caveat="Costs nothing to compute: it reads follow edges we already hold rather than fetching anything new."
      >
        {panelState({
          isLoading: suggestionsQuery.isLoading,
          error: suggestionsQuery.error,
          isEmpty: (suggestionsQuery.data?.suggestions.length ?? 0) === 0,
          severity: 'degraded',
          onRetry: () => suggestionsQuery.refetch(),
          errorTitle: 'Suggestions could not be loaded',
          errorBody: 'You can still request a username by hand.',
          empty: {
            title: 'No social data synced yet',
            body: 'Suggestions appear once follow lists are imported for the monitored profiles.',
          },
        }) ?? (
          <div data-testid="who-to-track-next">
            <Rows
              columns="minmax(0,1fr) minmax(0,1.2fr) 66px 96px"
              head={[
                'PROFILE',
                'FOLLOWED BY',
                ['FOLLOW', 'right'],
                ['ACTION', 'right'],
              ]}
              rows={(suggestionsQuery.data?.suggestions ?? []).map((suggestion) => {
                const canTrack =
                  suggestion.already_imported && suggestion.profile_id !== null;
                const busy =
                  (canTrack && busyProfileIds.has(suggestion.profile_id as number)) ||
                  busyUsernames.has(suggestion.username);
                const shown = suggestion.followed_by.slice(0, 3);
                const hidden = suggestion.followed_by.length - shown.length;
                const followsBack =
                  suggestion.follows_back_count > 0
                    ? ` · follows ${suggestion.follows_back_count} back`
                    : '';
                return {
                  cells: [
                    cell(`@${suggestion.username}`, { tone: 'var(--ink)' }),
                    cell(
                      `${shown.map((name) => `@${name}`).join(' ')}${hidden > 0 ? ` +${hidden} more` : ''}${followsBack}`,
                      { size: '10px', tone: 'var(--muted)' },
                    ),
                    cell(
                      `${suggestion.followed_by_count} of ${suggestionsQuery.data?.monitored_profiles ?? '—'}`,
                      { align: 'right', size: '10px' },
                    ),
                    cell(
                      canTrack ? (
                        <ActionButton
                          label="MONITOR"
                          busy={busy}
                          onClick={() =>
                            submitTrack(
                              suggestion.profile_id as number,
                              suggestion.username,
                              setSuggestionOutcome,
                            )
                          }
                          ariaLabel={`Monitor ${suggestion.username}`}
                        />
                      ) : (
                        <ActionButton
                          label="REQUEST"
                          busyLabel="REQUESTING…"
                          busy={busy}
                          onClick={() => submitRequest(suggestion.username, setSuggestionOutcome)}
                          ariaLabel={`Request ${suggestion.username}`}
                        />
                      ),
                      { align: 'right' },
                    ),
                  ],
                };
              })}
            />
            <OutcomeLine outcome={suggestionOutcome} />
          </div>
        )}
      </Panel>

      <Panel
        title="YOUR REQUEST STATUS"
        src="profile_access_requests.status"
        caveat="A rejected request is almost always a private account. Retrying will not change that, and the row says so rather than leaving it queued forever."
      >
        {panelState({
          isLoading: requestsQuery.isLoading,
          error: requestsQuery.error,
          isEmpty: (requestsQuery.data?.length ?? 0) === 0,
          severity: 'quiet',
          onRetry: () => requestsQuery.refetch(),
          errorTitle: 'Requests could not be loaded',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'No requests yet',
            body: 'Anything you ask for appears here with its state and what happens next.',
          },
        }) ?? (
          <Rows
            columns="minmax(0,1fr) 74px 82px minmax(0,1.2fr)"
            head={['ACCOUNT', ['ASKED', 'right'], ['STATE', 'right'], 'WHAT NEXT']}
            rows={(requestsQuery.data ?? []).map((request) => {
              const state = REQUEST_STATE[request.status];
              return {
                cells: [
                  cell(`@${request.requested_username}`, { tone: 'var(--ink)' }),
                  cell(new Date(request.requested_at).toLocaleDateString(), {
                    align: 'right',
                    size: '10px',
                    tone: 'var(--muted)',
                  }),
                  cell(state.label, { align: 'right', size: '10px', tone: state.tone }),
                  cell(state.next, {
                    font: 's',
                    size: '10px',
                    tone: 'var(--dim)',
                    wrap: true,
                  }),
                ],
              };
            })}
          />
        )}
      </Panel>

      <Panel
        title="HOW LONG A REQUEST ACTUALLY TAKES"
        src="profile_syncs durations"
        blurb="Measured from completed runs rather than promised."
        stats={
          latencyQuery.data && latencyQuery.data.runs
            ? [
                { big: duration(latencyQuery.data.median_seconds), unit: 'MEDIAN', tone: 'var(--accent)' },
                { big: duration(latencyQuery.data.worst_seconds), unit: 'WORST CASE' },
                { big: latencyQuery.data.runs, unit: 'RUNS MEASURED' },
              ]
            : undefined
        }
        caveat={latencyQuery.data?.caveat}
      >
        {panelState({
          isLoading: latencyQuery.isLoading || (selectionLoading && !enabled),
          error: latencyQuery.error,
          isEmpty: (latencyQuery.data?.runs ?? 0) === 0,
          onRetry: () => latencyQuery.refetch(),
          errorTitle: 'Latency could not be measured',
          errorBody: 'Every other panel on this tab is unaffected.',
          empty: {
            title: 'Nothing measurable yet',
            body: 'No completed sync carries both a start and an end time, so an estimate would be a promise rather than a figure.',
          },
        })}
      </Panel>

      {isAdmin ? (
        <Panel
          title="ADMIN · REQUEST QUEUE"
          src="profile_access_requests (admin scope)"
          blurb="Visible only under the admin scope. Everything below is somebody asking for a profile; a pending row takes an optional note and a decision."
          caveat="Approving a request queues a first read; it does not fetch anything on its own. The queue is worked through by the refresh schedule."
        >
          {panelState({
            isLoading: adminQueueQuery.isLoading,
            error: adminQueueQuery.error,
            isEmpty: (adminQueueQuery.data?.length ?? 0) === 0,
            onRetry: () => adminQueueQuery.refetch(),
            errorTitle: 'The admin queue could not be loaded',
            errorBody: 'Every other panel on this tab is unaffected.',
            empty: {
              title: 'No profile requests yet',
              body: 'Requests arrive here the moment any account asks for a username.',
            },
          }) ?? (
            <div>
              {(adminQueueQuery.data ?? []).map((request) => (
                <div
                  key={request.id}
                  className="border-b border-term-rule2 px-[10px] py-[7px]"
                >
                  <div className="flex items-baseline justify-between gap-[9px]">
                    <span className="terminal-num min-w-0 truncate text-t11 text-term-ink">
                      @{request.requested_username}
                    </span>
                    {/* The Letterboxd name when we hold one. Falling back to
                        the Clerk id is deliberate: a grandfathered account has
                        no linked username, and showing nothing would hide who
                        asked. */}
                    <span className="terminal-num shrink-0 text-t10 text-term-muted">
                      asked by{' '}
                      {request.requester_letterboxd_username
                        ? `@${request.requester_letterboxd_username}`
                        : request.requester_user_id}
                      {' · '}
                      {new Date(request.requested_at).toLocaleString()}
                    </span>
                    <span
                      className="terminal-num shrink-0 text-t10"
                      style={{ color: REQUEST_STATE[request.status].tone }}
                    >
                      {REQUEST_STATE[request.status].label}
                    </span>
                  </div>
                  {request.status === 'pending' ? (
                    <div className="mt-[6px] flex items-center gap-[6px]">
                      <input
                        value={adminNotes[request.id] ?? ''}
                        onChange={(event) =>
                          setAdminNotes((notes) => ({
                            ...notes,
                            [request.id]: event.target.value,
                          }))
                        }
                        placeholder="Optional note"
                        aria-label={`Note for ${request.requested_username}`}
                        className={inputClass}
                      />
                      <ActionButton
                        label="ACCEPT"
                        busy={busyRequestId === request.id && reviewMutation.isPending}
                        disabled={busyRequestId !== null && busyRequestId !== request.id}
                        tone="var(--ok)"
                        onClick={() =>
                          reviewMutation.mutate({ id: request.id, status: 'approved' })
                        }
                        ariaLabel={`Accept ${request.requested_username} for sync`}
                      />
                      <ActionButton
                        label="REJECT"
                        busy={busyRequestId === request.id && reviewMutation.isPending}
                        disabled={busyRequestId !== null && busyRequestId !== request.id}
                        tone="var(--bad)"
                        onClick={() =>
                          reviewMutation.mutate({ id: request.id, status: 'rejected' })
                        }
                        ariaLabel={`Reject ${request.requested_username}`}
                      />
                    </div>
                  ) : (
                    <p className="m-0 mt-[4px] font-term-sans text-t10 text-term-dim">
                      {request.note || 'No admin note.'} · {REQUEST_STATE[request.status].next}
                    </p>
                  )}
                </div>
              ))}
              <OutcomeLine outcome={queueOutcome} />
            </div>
          )}
        </Panel>
      ) : null}

      {isAdmin ? (
        <Panel
          title="ADMIN · RESIDENTIAL SYNC INTAKE"
          src="POST /upload/ · require_full_sync"
          blurb="VPS scraping is disabled; full syncs come only from the local residential runner. Approve requests, run the batch script, and land the ZIP bundles here."
          caveat="A successful upload fulfills matching approved profile requests. Owner-export publishing stays off on this path."
        >
          <Notes
            items={[
              {
                label: 'The loop',
                text: 'Approve pending requests · update sync-profiles.json on the residential machine · run scripts/batch_full_sync.py · upload the resulting ZIPs here if the runner did not.',
              },
            ]}
          />
          <div className="border-t border-term-rule2 px-[10px] py-[9px]" data-testid="residential-sync-upload">
            <label className="block">
              <span className="mb-[6px] block font-term-sans text-t10 font-semibold text-term-ink3">
                Residential full-sync ZIP bundles
              </span>
              <input
                ref={residentialInputRef}
                type="file"
                accept=".zip,application/zip"
                multiple
                aria-label="Residential full-sync ZIP bundles"
                disabled={residentialMutation.isPending}
                onChange={(event) => setResidentialFiles(event.target.files)}
                className="block w-full font-term-sans text-t10 text-term-dim file:mr-3 file:cursor-pointer file:rounded-[3px] file:border file:border-term-rule file:bg-transparent file:px-[8px] file:py-[4px] file:text-t95 file:font-bold file:text-term-ink3 hover:file:border-term-accent hover:file:text-term-accent"
              />
            </label>
            <div className="mt-[8px] flex items-center justify-between gap-[8px]">
              <span className="font-term-sans text-t10 text-term-dim">
                {residentialFiles?.length
                  ? `${count(residentialFiles.length, 'ZIP')} selected`
                  : 'Schema-v2 bundles produced from public Letterboxd HTML.'}
              </span>
              <ActionButton
                label="IMPORT FULL SYNC"
                busyLabel="UPLOADING…"
                busy={residentialMutation.isPending}
                disabled={!residentialFiles?.length}
                tone="var(--accent)"
                onClick={() => {
                  if (residentialFiles?.length) residentialMutation.mutate(residentialFiles);
                }}
              />
            </div>
          </div>
          <OutcomeLine outcome={residentialOutcome} />
        </Panel>
      ) : null}

      {isAdmin ? (
        <Panel
          title="ADMIN · OWNER EXPORT INTAKE"
          src="POST /upload/ · publish_owner_data"
          blurb="A profile owner can opt in by sharing their official Letterboxd export ZIP. It adds export-only history, tags, private account data, and deleted records a public page cannot expose."
          caveat="Export activity dates keep Letterboxd-export provenance and are never relabeled as confirmed viewing dates. The ZIP comes from letterboxd.com/user/exportdata/."
        >
          <div className="px-[10px] py-[9px]">
            <label className="block">
              <span className="mb-[6px] block font-term-sans text-t10 font-semibold text-term-ink3">
                Official export ZIP
              </span>
              <input
                ref={exportInputRef}
                type="file"
                accept=".zip,application/zip"
                multiple
                disabled={exportMutation.isPending}
                onChange={(event) => {
                  setExportFiles(event.target.files);
                  setHasOwnerConsent(false);
                }}
                className="block w-full font-term-sans text-t10 text-term-dim file:mr-3 file:cursor-pointer file:rounded-[3px] file:border file:border-term-rule file:bg-transparent file:px-[8px] file:py-[4px] file:text-t95 file:font-bold file:text-term-ink3 hover:file:border-term-accent hover:file:text-term-accent"
              />
            </label>
            <label className="mt-[8px] flex cursor-pointer items-start gap-[8px] border border-term-rule px-[8px] py-[6px] font-term-sans text-t10 leading-[15px] text-term-ink3">
              <input
                type="checkbox"
                checked={hasOwnerConsent}
                disabled={exportMutation.isPending}
                onChange={(event) => setHasOwnerConsent(event.target.checked)}
                className="mt-[2px] h-[12px] w-[12px] shrink-0 cursor-pointer accent-[var(--accent)] disabled:cursor-not-allowed"
              />
              <span>
                I confirm that I have the account owner&apos;s permission and their consent to
                publish all imported export contents — including private or deleted items — to
                visitors of this site.
              </span>
            </label>
            <div className="mt-[8px] flex items-center justify-between gap-[8px]">
              <span className="font-term-sans text-t10 text-term-dim">
                {exportFiles?.length
                  ? `${count(exportFiles.length, 'ZIP')} selected`
                  : 'Processed by the authenticated import endpoint.'}
              </span>
              <ActionButton
                label="IMPORT OWNER EXPORT"
                busyLabel="IMPORTING…"
                busy={exportMutation.isPending}
                disabled={!exportFiles?.length || !hasOwnerConsent}
                tone="var(--accent)"
                onClick={() => {
                  if (exportFiles?.length && hasOwnerConsent) exportMutation.mutate(exportFiles);
                }}
              />
            </div>
          </div>
          <OutcomeLine outcome={exportOutcome} />
        </Panel>
      ) : null}

      {isAdmin ? (
        <Panel
          title="ADMIN · ADD A PLACEHOLDER"
          src="POST /profiles/create"
          blurb="Creates an empty profile row a residential upload can fill later. Uploads also create missing profiles on their own, so this exists for queueing a name ahead of its data."
        >
          <form
            className="flex items-center gap-[7px] px-[10px] py-[9px]"
            onSubmit={(event) => {
              event.preventDefault();
              const username = placeholderUsername.trim();
              if (username) placeholderMutation.mutate(username);
            }}
          >
            <label className="min-w-0 flex-1">
              <span className="sr-only">Letterboxd username</span>
              <input
                ref={placeholderInputRef}
                type="text"
                value={placeholderUsername}
                onChange={(event) => setPlaceholderUsername(event.target.value)}
                placeholder="Letterboxd username"
                autoComplete="off"
                className={inputClass}
              />
            </label>
            <button
              type="submit"
              disabled={!placeholderUsername.trim() || placeholderMutation.isPending}
              className="shrink-0 rounded-[3px] border border-term-rule bg-transparent px-[9px] py-[5px] text-t95 font-bold tracking-tab text-term-ink3 hover:border-term-accent hover:text-term-accent disabled:cursor-not-allowed disabled:opacity-40"
            >
              {placeholderMutation.isPending ? 'ADDING…' : 'ADD PLACEHOLDER'}
            </button>
          </form>
          <OutcomeLine outcome={placeholderOutcome} />
        </Panel>
      ) : null}
    </>
  );
}
