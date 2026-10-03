import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeWorkspace, safeWorkspaceHref, EMPTY_WORKSPACE, OVERVIEW_PANEL_TITLES } from '../src/lib/workspacePreferences.ts';
import { csvCell, toCsv } from '../src/lib/csv.ts';

test('only versioned workspace preferences are accepted', () => {
  for (const value of [null, [], {}, { version: 2 }, 'not json']) assert.deepEqual(normalizeWorkspace(value), EMPTY_WORKSPACE);
});
test('groups are bounded, normalized, deduplicated and malformed rows excluded', () => {
  const result = normalizeWorkspace({ version: 1, groups: [null, {}, { id: '1', name: '  Cinema crew  ', profiles: ['ALPHA', 'alpha', 'bravo', '//evil', 123] }, { id: '1', name: 'duplicate', profiles: ['charlie'] }] });
  assert.deepEqual(result.groups, [{ id: '1', name: 'Cinema crew', profiles: ['alpha', 'bravo'] }]);
  assert.equal(normalizeWorkspace({ version: 1, groups: Array.from({ length: 40 }, (_, i) => ({ id: String(i), name: 'x', profiles: ['alpha'] })) }).groups.length, 30);
});
test('pins are local route URLs with supported filters, never executable or external', () => {
  for (const href of ['https://evil.test/films', '//evil.test/films', 'javascript:alert(1)', '/\\evil.test/films', '/api/private', '/films' + 'x'.repeat(6000)]) assert.equal(safeWorkspaceHref(href), null);
  assert.equal(safeWorkspaceHref('/films?tab=research&profiles=alpha&compare_profiles=bravo&research_from=2026-01-01&token=secret#insight-films-2'), '/films?tab=research&profiles=alpha&compare_profiles=bravo&research_from=2026-01-01#insight-films-2');
  assert.equal(safeWorkspaceHref('/overlaps?close=7#bad-hash'), '/overlaps?close=7');
});
test('only actual overview panels can be hidden and duplicate pins collapse', () => {
  const result = normalizeWorkspace({ version: 1, hiddenOverview: [...OVERVIEW_PANEL_TITLES, 'invented'], statistics: [{ title: 'A', href: '/people?subject=alpha' }, { title: 'A again', href: '/people?subject=alpha' }, { title: 'Bad', href: '//evil.test' }] });
  assert.deepEqual(result.hiddenOverview, OVERVIEW_PANEL_TITLES);
  assert.equal(result.statistics.length, 1);
});
test('CSV preserves quotes, commas, newlines and unknown values', () => {
  assert.equal(csvCell('Film, "Part Two"\n2026'), '"Film, ""Part Two""\n2026"');
  assert.equal(csvCell(null), '""');
  assert.equal(toCsv(['title', 'rating'], [['Film', 4.5]]), '\uFEFF"title","rating"\r\n"Film","4.5"\r\n');
});
test('spreadsheet formulas are inert even after leading whitespace', () => {
  for (const value of ['=1+1', '+SUM(1)', '-1+2', '@SUM(A1)', '  =cmd', '\t=1', '\r=2', '\n=3']) assert.ok(csvCell(value).startsWith('"\''));
});
