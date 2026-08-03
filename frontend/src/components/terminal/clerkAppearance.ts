/**
 * Clerk's card, dressed as a terminal panel.
 *
 * Everything is driven from the same CSS variables as the rest of the product,
 * so the sign-in form follows the theme toggle rather than being pinned to one
 * of the two. Flat borders, no radius beyond 3px, no shadow.
 */
export const terminalClerkAppearance = {
  variables: {
    colorPrimary: 'var(--accent)',
    colorBackground: 'var(--panel)',
    colorText: 'var(--ink)',
    colorTextSecondary: 'var(--ink3)',
    colorInputBackground: 'var(--bg2)',
    colorInputText: 'var(--ink)',
    colorDanger: 'var(--bad)',
    colorSuccess: 'var(--ok)',
    borderRadius: '3px',
    fontFamily: 'var(--font-sans), system-ui, sans-serif',
  },
  elements: {
    rootBox: 'mx-auto',
    card: 'border border-[color:var(--rule)] bg-[color:var(--panel)] shadow-none',
    headerTitle: 'text-[color:var(--ink)]',
    headerSubtitle: 'text-[color:var(--ink3)]',
    socialButtonsBlockButton:
      'border-[color:var(--rule)] text-[color:var(--ink2)] hover:bg-[color:var(--panelhd)]',
    dividerLine: 'bg-[color:var(--rule)]',
    dividerText: 'text-[color:var(--muted)]',
    formFieldLabel: 'text-[color:var(--ink3)]',
    formFieldInput:
      'bg-[color:var(--bg2)] border-[color:var(--rule)] text-[color:var(--ink)] placeholder:text-[color:var(--dim)]',
    formButtonPrimary:
      'bg-[color:var(--accent)] text-[color:var(--onaccent)] hover:opacity-90 shadow-none',
    footerActionLink: 'text-[color:var(--accent)] hover:text-[color:var(--accent2)]',
    footer: 'bg-[color:var(--panelhd)]',
  },
} as const;
