import { redirect } from 'next/navigation';

/**
 * The old profile manager's address. The page moved into Data › Profiles when
 * the last section left the legacy layout, but the path stays: sign-up still
 * force-redirects here, and bookmarks and the production canary knew it first.
 * A server-side redirect keeps the anonymous contract intact too -- middleware
 * bounces signed-out visitors to sign-in before this ever runs.
 */
export default async function ProfilesRedirect({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = new URLSearchParams({ tab: 'profiles' });
  const resolved = await searchParams;
  if (resolved.onboarding === '1') params.set('onboarding', '1');
  if (resolved.add === 'true') params.set('add', 'true');
  redirect(`/data?${params.toString()}`);
}
