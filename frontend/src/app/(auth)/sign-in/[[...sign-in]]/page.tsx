import { SignIn } from '@clerk/nextjs';

import { terminalClerkAppearance } from '../../../../components/terminal/clerkAppearance';

export default function SignInPage() {
  return (
    <SignIn fallbackRedirectUrl="/overview" appearance={terminalClerkAppearance} />
  );
}
