import Layout from '../../components/Layout';
import { AdminScopeProvider } from '../../hooks/useAdminScope';

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AdminScopeProvider>
      <Layout>{children}</Layout>
    </AdminScopeProvider>
  );
}
