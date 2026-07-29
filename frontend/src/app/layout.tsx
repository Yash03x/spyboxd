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
    <ClerkProvider afterSignOutUrl="/sign-in">
      <html lang="en">
        <body>
          <Providers>{children}</Providers>
        </body>
      </html>
    </ClerkProvider>
  );
}
