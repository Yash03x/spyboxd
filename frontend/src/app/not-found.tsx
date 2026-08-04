import Link from 'next/link';

/**
 * Signed-out traffic never sees this — the middleware bounces unknown paths to
 * sign-in with everything else. A signed-in user with a stale bookmark does,
 * and "this page does not exist" is a different fact from "you cannot see
 * this", so it is stated rather than left to a blank default.
 */
export default function NotFound() {
  return (
    <main
      style={{
        minHeight: '100vh',
        display: 'grid',
        placeItems: 'center',
        background: 'var(--bg, #101014)',
        color: 'var(--ink, #e8e6e3)',
        fontFamily: 'ui-monospace, monospace',
        padding: '24px',
      }}
    >
      <div style={{ maxWidth: '480px' }}>
        <p style={{ margin: 0, fontSize: '11px', letterSpacing: '0.08em', opacity: 0.6 }}>
          ▸ 404
        </p>
        <h1 style={{ margin: '8px 0 0', fontSize: '15px', fontWeight: 600 }}>
          No page lives at this address
        </h1>
        <p style={{ margin: '10px 0 0', fontSize: '12.5px', lineHeight: 1.6, opacity: 0.8 }}>
          The six sections are Overview, Overlaps, People, Tonight, Films and Data. The
          pre-redesign paths all redirect, so a link that lands here never existed.
        </p>
        <p style={{ marginTop: '16px' }}>
          <Link href="/overview" style={{ color: 'inherit', fontSize: '11px', letterSpacing: '0.06em' }}>
            GO TO OVERVIEW →
          </Link>
        </p>
      </div>
    </main>
  );
}
