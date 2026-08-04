'use client';

/**
 * Last resort: a throw in the root layout itself, where error.tsx cannot
 * mount. Must render its own <html> because nothing else survived.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: '100vh',
          display: 'grid',
          placeItems: 'center',
          background: '#101014',
          color: '#e8e6e3',
          fontFamily: 'ui-monospace, monospace',
        }}
      >
        <div style={{ maxWidth: '480px', padding: '24px' }}>
          <h1 style={{ margin: 0, fontSize: '15px', fontWeight: 600 }}>Spyboxd could not start</h1>
          <p style={{ margin: '10px 0 0', fontSize: '12.5px', lineHeight: 1.6, opacity: 0.8 }}>
            The application shell itself failed to render. Nothing about your data changed.
            {error.digest ? ` Reference: ${error.digest}.` : ''}
          </p>
          <button
            type="button"
            onClick={reset}
            style={{
              marginTop: '16px',
              padding: '7px 14px',
              fontSize: '11px',
              background: 'transparent',
              color: 'inherit',
              border: '1px solid currentColor',
              cursor: 'pointer',
            }}
          >
            RELOAD
          </button>
        </div>
      </body>
    </html>
  );
}
