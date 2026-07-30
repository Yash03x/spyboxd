import { SignUp } from '@clerk/nextjs';

export default function SignUpPage() {
  return (
    <div className="min-h-screen px-4 py-10 sm:px-6">
      <div className="mx-auto grid min-h-[calc(100vh-5rem)] max-w-5xl items-center gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(24rem,28rem)]">
        <section className="max-w-xl" aria-labelledby="signup-introduction-title">
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-cinema-300">Create your account</p>
          <h1 id="signup-introduction-title" className="mt-3 text-4xl font-bold leading-tight text-white sm:text-5xl">
            Your Letterboxd username is your Spyboxd username.
          </h1>
          <p className="mt-5 text-base leading-7 text-white/60">
            Use the exact username from your Letterboxd profile. After sign-up, Spyboxd will automatically monitor it if it is already synced, or request it for the next residential data refresh.
          </p>
          <p className="mt-4 text-sm leading-6 text-white/45">
            Letterboxd usernames are 2–15 characters and use only letters, numbers, or underscores. Entering a username links the public profile data; it does not verify ownership of the Letterboxd account.
          </p>
        </section>
        <SignUp
          forceRedirectUrl="/profiles?onboarding=1"
          appearance={{
            elements: {
              rootBox: 'mx-auto w-full',
              card: 'bg-black/30 backdrop-blur-xl border border-white/10 shadow-2xl',
              headerTitle: 'text-white',
              headerSubtitle: 'text-white/60',
              socialButtonsBlockButton: 'border-white/20 text-white hover:bg-white/10',
              dividerLine: 'bg-white/10',
              dividerText: 'text-white/40',
              formFieldLabel: 'text-white/70',
              formFieldInput: 'bg-white/5 border-white/20 text-white placeholder:text-white/30 focus:border-cinema-400',
              formButtonPrimary: 'bg-cinema-500 hover:bg-cinema-600',
              footerActionLink: 'text-cinema-400 hover:text-cinema-300',
            },
          }}
        />
      </div>
    </div>
  );
}
