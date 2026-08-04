'use client';

/**
 * The boundary above every route. Each panel already catches its own query
 * errors and degrades alone — this exists for everything outside a panel: a
 * throw in a layout, a shell component, a hook. Without it, that class of
 * error unmounted the whole tree to a blank page, which is the failure mode
 * this product is least allowed to have: a blank page carries no caveat.
 */
export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
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
          ▸ SOMETHING OUTSIDE A PANEL FAILED
        </p>
        <h1 style={{ margin: '8px 0 0', fontSize: '15px', fontWeight: 600 }}>
          This section could not render
        </h1>
        <p style={{ margin: '10px 0 0', fontSize: '12.5px', lineHeight: 1.6, opacity: 0.8 }}>
          A single panel failing degrades alone; this was something structural. Nothing about your
          data changed — the store is append-only, and a render error writes nothing.
          {error.digest ? ` Reference: ${error.digest}.` : ''}
        </p>
        <button
          type="button"
          onClick={reset}
          style={{
            marginTop: '16px',
            padding: '7px 14px',
            fontSize: '11px',
            letterSpacing: '0.06em',
            background: 'transparent',
            color: 'inherit',
            border: '1px solid currentColor',
            cursor: 'pointer',
          }}
        >
          TRY AGAIN
        </button>
      </div>
    </main>
  );
}
