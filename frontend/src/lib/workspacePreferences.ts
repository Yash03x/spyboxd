export const OVERVIEW_PANEL_TITLES = [
  'THE GROUP, IN FIVE NUMBERS', 'THE LATEST CHANGES WE DETECTED', 'WHO WATCHES WITH WHOM',
  'EVERYONE WE ARE WATCHING', 'THE LAST TWELVE MONTHS', 'HOW THE GROUP RATES',
  'MARATHON DAYS', 'EXPLORE BEYOND THE OVERVIEW',
];
export interface SavedGroup { id: string; name: string; profiles: string[] }
export interface SavedStatistic { title: string; href: string }
export interface WorkspacePreferences { version: 1; groups: SavedGroup[]; statistics: SavedStatistic[]; hiddenOverview: string[] }
export const EMPTY_WORKSPACE: WorkspacePreferences = { version: 1, groups: [], statistics: [], hiddenOverview: [] };
const ROUTES = new Set(['/overview', '/overlaps', '/people', '/films', '/tonight', '/data', '/anime']);
const QUERY_KEYS = new Set(['tab', 'profiles', 'subject', 'region', 'close', 'gap_days', 'tier', 'pick', 'rewatch', 'max_runtime', 'genre', 'availability', 'trait', 'trait_order', 'trait_rows', 'trend_year', 'compare_profiles', 'research_from', 'research_to', 'research_basis', 'research_dimension', 'research_trait', 'research_q', 'research_sort', 'research_page']);
for (const key of ['anime_snapshot', 'anime_q', 'anime_id', 'anime_status', 'anime_format', 'anime_score', 'anime_year', 'anime_issue', 'anime_sort', 'anime_page', 'anime_timeline_year']) QUERY_KEYS.add(key);
for (const key of ['anime_genre', 'anime_studio', 'anime_scope', 'anime_trait_min', 'anime_pick_format', 'anime_pick_max_minutes']) QUERY_KEYS.add(key);

export function safeWorkspaceHref(value: unknown): string | null {
  if (typeof value !== 'string' || value.length > 6000 || !value.startsWith('/') || value.startsWith('//')) return null;
  try {
    const url = new URL(value, 'https://workspace.invalid');
    if (url.origin !== 'https://workspace.invalid' || !ROUTES.has(url.pathname)) return null;
    for (const key of [...url.searchParams.keys()]) if (!QUERY_KEYS.has(key)) url.searchParams.delete(key);
    if (url.hash && !/^#insight-[a-z0-9-]+$/.test(url.hash)) url.hash = '';
    return url.pathname + url.search + url.hash;
  } catch { return null; }
}

export function normalizeWorkspace(value: unknown): WorkspacePreferences {
  if (!value || typeof value !== 'object' || (value as { version?: unknown }).version !== 1) return EMPTY_WORKSPACE;
  const input = value as Record<string, unknown>;
  const groups: SavedGroup[] = [];
  for (const raw of Array.isArray(input.groups) ? input.groups.slice(0, 30) : []) {
    if (!raw || typeof raw !== 'object' || typeof raw.id !== 'string' || typeof raw.name !== 'string' || !Array.isArray(raw.profiles)) continue;
    const profiles = [...new Set<string>(raw.profiles.filter((name: unknown): name is string => typeof name === 'string' && /^[a-z0-9_]{2,50}$/i.test(name)).map((name: string) => name.toLowerCase()))].slice(0, 50);
    const name = raw.name.trim().slice(0, 50);
    if (name && profiles.length && raw.id.length <= 100 && !groups.some((group) => group.id === raw.id)) groups.push({ id: raw.id, name, profiles });
  }
  const statistics: SavedStatistic[] = [];
  for (const raw of Array.isArray(input.statistics) ? input.statistics.slice(0, 40) : []) {
    if (!raw || typeof raw.title !== 'string') continue;
    const href = safeWorkspaceHref(raw.href);
    if (href && !statistics.some((statistic) => statistic.href === href)) statistics.push({ href, title: raw.title.trim().slice(0, 150) });
  }
  const hidden = Array.isArray(input.hiddenOverview) ? input.hiddenOverview : [];
  return { version: 1, groups, statistics, hiddenOverview: OVERVIEW_PANEL_TITLES.filter((title) => hidden.includes(title)) };
}
