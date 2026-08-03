import { SignUp } from '@clerk/nextjs';

import { terminalClerkAppearance } from '../../../../components/terminal/clerkAppearance';

export default function SignUpPage() {
  return (
    <div className="mx-auto grid w-full max-w-5xl items-center gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(24rem,28rem)]">
      <section className="max-w-xl" aria-labelledby="signup-introduction-title">
        <p className="text-t9 font-bold uppercase tracking-crumb text-term-accent">
          Create your account
        </p>
        <h1
          id="signup-introduction-title"
          className="m-0 mt-3 font-term-sans text-t22 font-bold tracking-head text-term-ink sm:text-t30"
        >
          Your Letterboxd username is your Spyboxd username.
        </h1>
        <p className="m-0 mt-4 font-term-sans text-t115 text-term-ink3">
          Use the exact username from your Letterboxd profile. After sign-up, Spyboxd will
          automatically monitor it if it is already synced, or request it for the next full refresh.
        </p>
        <p className="m-0 mt-3 font-term-sans text-t105 text-term-dim">
          Letterboxd usernames are 2–15 characters and use only letters, numbers, or underscores.
          Entering a username links the public profile data; it does not verify ownership of the
          Letterboxd account.
        </p>
      </section>
      <SignUp
        forceRedirectUrl="/profiles?onboarding=1"
        appearance={{
          ...terminalClerkAppearance,
          elements: { ...terminalClerkAppearance.elements, rootBox: 'mx-auto w-full' },
        }}
      />
    </div>
  );
}
