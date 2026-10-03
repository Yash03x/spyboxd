'use client';

import React, { useEffect, useId, useState } from 'react';
import Panel, { type PanelProps } from './Panel';
import { useWorkspacePreferences } from '../../hooks/useWorkspacePreferences';

/** A searchable outline, derived from the panels actually on this page. */
export default function PanelCollection({ children, ready = true, customizable = false, pinParams }: { children: React.ReactNode; ready?: boolean; customizable?: boolean; pinParams?: Record<string, string | string[]> }) {
  const { preferences, save } = useWorkspacePreferences();
  const [storageMessage, setStorageMessage] = useState('');
  const prefix = useId().replace(/:/g, '');
  const [query, setQuery] = useState('');
  const nodes = React.Children.toArray(children);
  // Anchors must survive reloads and different hydration paths. useId is for
  // the input label below, not a shareable identifier for a statistic.
  const panels = nodes.flatMap((node, index) => React.isValidElement<PanelProps>(node) && node.type === Panel
    ? [{ node, id: `insight-${node.props.title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')}-${index}`, title: node.props.title, index }]
    : []);
  const words = query.toLowerCase().trim().split(/\s+/).filter(Boolean);
  const visiblePanels = panels.filter(({ title }) => !customizable || !preferences.hiddenOverview.includes(title));
  const matches = visiblePanels.filter(({ node }) => words.every((word) => `${node.props.title} ${node.props.blurb ?? ''}`.toLowerCase().includes(word)));
  const panelIds = new Map(panels.map(({ index, id }) => [index, id]));

  useEffect(() => {
    // On a bookmarked/reloaded URL the browser searches for the anchor before
    // authenticated data mounts. Wait for the initial queries so loading panels
    // above the target cannot move it out of view after the jump.
    if (!ready || !window.location.hash.startsWith('#insight-')) return;
    document.getElementById(window.location.hash.slice(1))?.scrollIntoView({ behavior: 'instant', block: 'start' });
  }, [ready, preferences.hiddenOverview]);

  return <>
    <div className="col-span-full border-b border-term-rule pb-3 font-term-sans">
      {customizable ? <details className="mb-2"><summary className="cursor-pointer py-2 text-t115 text-term-accent">Customise your overview</summary><p className="text-t11 text-term-muted">Choose the panels you want to see. This changes your browser&apos;s layout, not the underlying data.</p><div className="flex flex-wrap gap-3">{panels.map(({ title }) => <label key={title} className="flex items-center gap-2 text-t11"><input type="checkbox" aria-label={`Show ${title}`} checked={!preferences.hiddenOverview.includes(title)} onChange={(event) => {
        const shown = event.target.checked;
        setStorageMessage(save((current) => ({ ...current, hiddenOverview: shown ? current.hiddenOverview.filter((value) => value !== title) : [...current.hiddenOverview, title] })) ? '' : 'Browser storage is unavailable.');
      }} />{title}</label>)}</div><button className="mt-3 rounded border border-term-rule px-3 py-2 text-t11 text-term-accent" onClick={() => setStorageMessage(save((current) => ({ ...current, hiddenOverview: [] })) ? '' : 'Browser storage is unavailable.')}>Restore all overview panels</button><p role="status" className="text-t11 text-term-muted">{storageMessage}</p></details> : null}
      <details>
        <summary className="cursor-pointer py-2 text-t115 font-semibold text-term-accent">Jump to a statistic · {visiblePanels.length} panels</summary>
        <label htmlFor={`${prefix}-search`} className="mt-2 block text-t11 text-term-ink3">Find a statistic on this page</label>
        <input id={`${prefix}-search`} type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search ratings, genres, rewatches…" className="my-2 w-full max-w-[34rem] rounded-[3px] border border-term-rule bg-term-bg px-3 py-2 text-t115 text-term-ink" />
        <p role="status" className="my-2 text-t105 text-term-muted">{matches.length ? `${matches.length} matching panels. Choose one to jump straight to the evidence.` : 'No matching panels. Try another term.'}</p>
        <nav aria-label="Statistics on this page" className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {matches.map(({ id, title }) => <a key={id} href={`#${id}`} className="py-1 text-t11 text-term-accent">{title}</a>)}
        </nav>
      </details>
      {customizable && preferences.hiddenOverview.length ? <p className="text-t11 text-term-muted">{preferences.hiddenOverview.length} overview panels hidden. If a pinned statistic is hidden, use Customise your overview to show it again.</p> : null}
    </div>
    {nodes.map((node, index) => customizable && React.isValidElement<PanelProps>(node) && preferences.hiddenOverview.includes(node.props.title) ? null : React.isValidElement<PanelProps>(node) && panelIds.has(index)
      ? React.cloneElement(node, { panelId: panelIds.get(index), pinParams }) : node)}
  </>;
}
