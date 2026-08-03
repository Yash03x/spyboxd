import Link from 'next/link';

/**
 * Sign-in and sign-up sit on the same warm/dark surface as the rest of the
 * product and follow the same theme. Clerk's own card is themed through the
 * `appearance` prop on each page against the same CSS variables.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="terminal-root flex min-h-screen flex-col">
      <header className="flex h-[34px] items-center gap-[10px] border-b border-term-rule bg-term-bg2 px-3 text-t105">
        <Link href="/" className="flex items-center gap-[10px] no-underline hover:no-underline">
          <span className="grid h-[22px] w-[22px] place-items-center rounded-[3px] bg-term-accent text-[11px] font-extrabold text-term-onaccent">
            S
          </span>
          <span className="font-bold tracking-crumb text-term-accent">SPYBOXD</span>
        </Link>
        <span className="text-term-dim2">›</span>
        <span className="text-term-ink3">ACCOUNT</span>
      </header>
      <div className="flex flex-1 items-center justify-center px-4 py-10">{children}</div>
    </div>
  );
}
