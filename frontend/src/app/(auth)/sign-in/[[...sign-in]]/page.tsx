import { SignIn } from '@clerk/nextjs';

export default function SignInPage() {
  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <SignIn
        fallbackRedirectUrl="/dashboard"
        appearance={{
          elements: {
            rootBox: 'mx-auto',
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
  );
}
