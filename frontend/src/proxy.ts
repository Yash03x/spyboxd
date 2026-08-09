import { clerkMiddleware } from '@clerk/nextjs/server';

const PUBLIC_ROUTE_PATTERNS = [
  /^\/$/,
  /^\/sign-in(?:\/.*)?$/,
  /^\/sign-up(?:\/.*)?$/,
];

export default clerkMiddleware(async (auth, request) => {
  // Playwright builds use a dedicated, non-deployed artifact. Requiring both
  // the job-only environment flag and an explicit cookie keeps anonymous-route
  // tests possible while ensuring a stray browser cookie cannot bypass auth.
  const isE2eAuthenticated =
    process.env.SPYBOXD_E2E_AUTH_BYPASS === '1'
    && request.cookies.get('spyboxd-e2e-auth')?.value === '1';

  const isPublicRoute = PUBLIC_ROUTE_PATTERNS.some((pattern) => pattern.test(request.nextUrl.pathname));

  if (!isPublicRoute && !isE2eAuthenticated) {
    await auth.protect();
  }
});

export const config = {
  matcher: [
    // `txt` and `xml` belong with the other static extensions: without
    // them /robots.txt went through Clerk and answered a crawler with a
    // 307 to /sign-in, so the file we ship to say what may be indexed
    // was itself unreadable.
    '/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|txt|xml|docx?|xlsx?|zip|webmanifest)).*)',
    '/(api|trpc)(.*)',
    '/__clerk/(.*)',
  ],
};
