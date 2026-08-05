import type { Metadata } from 'next';
import { ClerkProvider } from '@clerk/nextjs';
import Providers from './providers';
import { ibmPlexSans, jetbrainsMono } from './fonts';
import { BUILD_REVISION } from '../buildRevision';
import { THEME_INIT_SCRIPT } from '../components/terminal/theme';
import '../index.css';

export const metadata: Metadata = {
  title: { default: 'Spyboxd', template: '%s | Spyboxd' },
  description: 'Spyboxd — analytics and insights for Letterboxd profiles',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider
      afterSignOutUrl="/"
      localization={{
        formFieldLabel__username: 'Letterboxd username',
        formFieldInputPlaceholder__username: 'e.g. yash03x',
        formFieldLabel__emailAddress_username: 'Email or Letterboxd username',
        formFieldInputPlaceholder__emailAddress_username: 'Enter email or Letterboxd username',
      }}
    >
      <html
        lang="en"
        className={`${jetbrainsMono.variable} ${ibmPlexSans.variable}`}
        suppressHydrationWarning
      >
        <head>
          {/* Sets data-theme before first paint. Without it the page renders in
              the default theme and then snaps to the stored one, which on a
              dense terminal layout is the whole screen flashing. */}
          <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
        </head>
        {/* The build's own revision, stamped where an anonymous GET can read
            it: the root layout is server-rendered on every page, so the
            production canary can compare this against the API's /health
            revision without signing in. */}
        <body data-build-revision={BUILD_REVISION}>
          <Providers>{children}</Providers>
        </body>
      </html>
    </ClerkProvider>
  );
}
