/**
 * The Git revision this frontend was built from, inlined at build time.
 *
 * CI sets NEXT_PUBLIC_BUILD_REVISION to the bundle's own commit before
 * `npm run build`, so the value is a property of the artifact rather than of
 * whatever is checked out where it happens to run. The API already answers
 * /health with its revision; this is the web half of the same question, and
 * the production canary asserts the two agree after every deploy. Local dev
 * builds carry 'dev'.
 */
export const BUILD_REVISION: string = process.env.NEXT_PUBLIC_BUILD_REVISION ?? 'dev';

export const SHORT_BUILD_REVISION: string =
  BUILD_REVISION === 'dev' ? 'dev' : BUILD_REVISION.slice(0, 7);
