import { AdminScopeProvider } from '../../hooks/useAdminScope';

/**
 * The redesigned sections own their whole chrome -- rail, status bar, tab row
 * -- so this layout deliberately does not wrap them in the legacy `Layout`
 * component. Both shells coexist while the remaining sections are moved across.
 */
export default function TerminalLayout({ children }: { children: React.ReactNode }) {
  return <AdminScopeProvider>{children}</AdminScopeProvider>;
}
