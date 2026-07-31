'use client';

import React from 'react';

import { useAdminScope } from '../hooks/useAdminScope';

const AdminScopeToggle: React.FC = () => {
  const { isAdmin, scope, setScope } = useAdminScope();
  if (!isAdmin) return null;

  return (
    <div className="inline-flex rounded-xl border border-white/10 bg-black/20 p-1" aria-label="Data scope">
      <button
        type="button"
        aria-pressed={scope === 'tracked'}
        onClick={() => setScope('tracked')}
        className={`rounded-lg px-3 py-2 text-xs font-semibold transition-colors ${scope === 'tracked' ? 'bg-cinema-500 text-white' : 'text-white/55 hover:text-white'}`}
      >
        Monitored
      </button>
      <button
        type="button"
        aria-pressed={scope === 'global'}
        onClick={() => setScope('global')}
        className={`rounded-lg px-3 py-2 text-xs font-semibold transition-colors ${scope === 'global' ? 'bg-cinema-500 text-white' : 'text-white/55 hover:text-white'}`}
      >
        Global admin
      </button>
    </div>
  );
};

export default AdminScopeToggle;
