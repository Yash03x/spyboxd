/**
 * The information architecture of the redesign: six question-named sections,
 * nineteen tabs. This file is the single source of truth for the rail, the
 * status-bar breadcrumb, the tab row, the panel counts and the route map --
 * every one of those reads from here rather than repeating the list.
 */

export type SectionId = 'overview' | 'overlaps' | 'people' | 'tonight' | 'films' | 'data';

export interface TabDef {
  /** URL value, e.g. `?tab=echoes`. */
  id: string;
  label: string;
  /**
   * How many panels the tab holds; shown beside the label in the tab row.
   *
   * Counted from what the page actually renders, not from what the handoff
   * planned. Three of these were transcribed from the design document and then
   * drifted as panels were added; a fourth (One person) drifted again when a
   * panel rendered conditionally — it appeared for subjects whose import
   * reported a limitation and vanished for the rest, so the same badge was
   * right for one subject and wrong for another. That panel always renders
   * now, with "nothing declared out of reach" as its honest empty state. A
   * badge in a product whose whole argument is that its numbers are true
   * cannot be a rough estimate, and e2e/panel-counts.spec.ts holds every one
   * of these to the rendered count.
   *
   * Data › Profiles is the one tab whose panel count is not fixed: an admin
   * sees an extra request-queue panel. The number here is what every reader
   * gets; the admin panel is labelled as an addition.
   */
  panels: number;
}

export interface SectionDef {
  id: SectionId;
  /** Two-digit ordinal shown in the status bar crumb. */
  ordinal: string;
  name: string;
  /** lucide-react icon name, resolved in Rail.tsx. */
  icon: 'layout-grid' | 'radio' | 'users-round' | 'popcorn' | 'clapperboard' | 'database';
  question: string;
  blurb: string;
  tabs: TabDef[];
  /**
   * The pre-redesign route a section is still being served from, if any.
   * Nothing sets it now that all six have landed; it stays because the next
   * migration will want the same escape hatch -- a half-migrated product that
   * still works beats a fully-migrated one that 404s.
   */
  legacyPath?: string;
}

export const SECTIONS: SectionDef[] = [
  {
    id: 'overview',
    ordinal: '01',
    name: 'Overview',
    icon: 'layout-grid',
    question: 'What happened while I was away?',
    blurb:
      'The only screen that answers a question you did not ask. Everything here is either a change since your last visit or a number that frames the rest of the product.',
    tabs: [{ id: 'now', label: 'EVERYTHING', panels: 8 }],
  },
  {
    id: 'overlaps',
    ordinal: '02',
    name: 'Overlaps',
    icon: 'radio',
    question: 'Who watched the same thing, and when?',
    blurb:
      'Was Spy Signals. Same film, close in time — the core of the product, plus the honest account of how sure we are about each one.',
    tabs: [
      { id: 'together', label: 'TOGETHER', panels: 7 },
      { id: 'echoes', label: 'ECHOES', panels: 4 },
      { id: 'when', label: 'WHEN', panels: 4 },
      { id: 'sure', label: 'HOW SURE', panels: 3 },
    ],
  },
  {
    id: 'people',
    ordinal: '03',
    name: 'People',
    icon: 'users-round',
    question: 'What is this person like, and how do they relate?',
    blurb:
      'Merges Analysis, Compare and Network. Three doors into the same subject become one destination with four tabs.',
    tabs: [
      { id: 'one', label: 'ONE PERSON', panels: 29 },
      { id: 'two', label: 'TWO PEOPLE', panels: 11 },
      { id: 'circle', label: 'THE CIRCLE', panels: 7 },
      { id: 'reach', label: 'REACH', panels: 6 },
    ],
  },
  {
    id: 'tonight',
    ordinal: '04',
    name: 'Tonight',
    icon: 'popcorn',
    question: 'What should we actually watch?',
    blurb:
      'Was Watch Together. The only section with a deadline in it — everything here is meant to end in a decision within the next hour.',
    tabs: [
      { id: 'picks', label: 'PICKS', panels: 4 },
      { id: 'lists', label: 'LISTS', panels: 4 },
      { id: 'leaving', label: 'LEAVING SOON', panels: 3 },
    ],
  },
  {
    id: 'films',
    ordinal: '05',
    name: 'Films',
    icon: 'clapperboard',
    question: 'What does this group actually watch?',
    blurb:
      'What this group watches as a library rather than as people — previously scattered across Analysis, Watch Together and the signal indexes.',
    tabs: [
      { id: 'library', label: 'THE LIBRARY', panels: 5 },
      { id: 'taste', label: 'TASTE MAP', panels: 5 },
      { id: 'gaps', label: 'GAPS', panels: 2 },
    ],
  },
  {
    id: 'data',
    ordinal: '06',
    name: 'Data',
    icon: 'database',
    question: 'Where did all this come from, and what is missing?',
    blurb:
      'Was My Profiles. Choosing who you follow sits next to the sync health that decides what you actually get, and next to the honest inventory of what we cannot read.',
    tabs: [
      { id: 'profiles', label: 'PROFILES', panels: 5 },
      { id: 'refreshes', label: 'REFRESHES', panels: 4 },
      { id: 'missing', label: "WHAT'S MISSING", panels: 4 },
      { id: 'lost', label: 'LOST & FOUND', panels: 3 },
    ],
  },
];

export function getSection(id: string | undefined): SectionDef {
  return SECTIONS.find((section) => section.id === id) ?? SECTIONS[0];
}

/**
 * Resolve a `?tab=` value against a section, falling back to the section's
 * first tab. An unknown tab is a typo or a stale bookmark, not an error worth
 * a 404 -- landing on the first tab is what the reader wanted anyway.
 */
export function getTab(section: SectionDef, tabId: string | null | undefined): TabDef {
  return section.tabs.find((tab) => tab.id === tabId) ?? section.tabs[0];
}

/**
 * Deep link used by cross-panel "where to look next" rows. Falls back to the
 * section's legacy route while it is still being moved across, so a link the
 * redesign promises never lands on a 404.
 */
export function sectionHref(id: SectionId, tabId?: string): string {
  const section = SECTIONS.find((entry) => entry.id === id);
  if (section?.legacyPath) return section.legacyPath;
  return tabId ? `/${id}?tab=${tabId}` : `/${id}`;
}
