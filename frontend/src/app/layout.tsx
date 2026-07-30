import type { Metadata } from 'next';
import { ClerkProvider } from '@clerk/nextjs';
import Providers from './providers';
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
      <html lang="en">
        <body>
          <Providers>{children}</Providers>
        </body>
      </html>
    </ClerkProvider>
  );
}
