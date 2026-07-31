'use client';

import React, { useState, useEffect } from 'react';
import Image from 'next/image';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { SignOutButton, UserButton, useAuth } from '@clerk/nextjs';
import { motion, AnimatePresence } from 'framer-motion';
import {
  HomeIcon,
  ChartBarIcon,
  UserGroupIcon,
  SignalIcon,
  ScaleIcon,
} from '@heroicons/react/24/outline';
import {
  HomeIcon as HomeIconSolid,
  ChartBarIcon as ChartBarIconSolid,
  SignalIcon as SignalIconSolid,
  ScaleIcon as ScaleIconSolid,
} from '@heroicons/react/24/solid';
import { LogOut, Menu, UsersRound, Waypoints, X } from 'lucide-react';
import { useCurrentUser } from '../hooks/useCurrentUser';
import AdminScopeToggle from './AdminScopeToggle';

interface LayoutProps {
  children: React.ReactNode;
}

const NAVIGATION_ITEMS = [
  {
    path: '/dashboard',
    label: 'My Dashboard',
    icon: HomeIcon,
    activeIcon: HomeIconSolid,
    description: 'Your Profile Overview',
  },
  {
    path: '/spy-signals',
    label: 'Spy Signals',
    icon: SignalIcon,
    activeIcon: SignalIconSolid,
    description: 'Same-day & Gap Alerts',
  },
  {
    path: '/compare',
    label: 'Compare',
    icon: ScaleIcon,
    activeIcon: ScaleIconSolid,
    description: 'Understand Overlap',
  },
  {
    path: '/watch-together',
    label: 'Watch Together',
    icon: UsersRound,
    activeIcon: UsersRound,
    description: 'Find a Group Pick',
  },
  {
    path: '/network',
    label: 'Network',
    icon: Waypoints,
    activeIcon: Waypoints,
    description: 'The Follow Graph',
  },
  {
    path: '/profiles',
    label: 'My Profiles',
    icon: UserGroupIcon,
    activeIcon: UserGroupIcon,
    description: 'Track & Manage',
  },
  {
    path: '/analysis',
    label: 'Analysis',
    icon: ChartBarIcon,
    activeIcon: ChartBarIconSolid,
    description: 'Profile Deep Dive',
  },
] as const;

const Layout: React.FC<LayoutProps> = ({ children }) => {
  const pathname = usePathname();
  const { isSignedIn } = useAuth();
  const currentUserQuery = useCurrentUser(Boolean(isSignedIn));
  const [isLoaded, setIsLoaded] = useState(false);
  const [currentTime, setCurrentTime] = useState<Date | null>(null);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useEffect(() => {
    setIsLoaded(true);
    setCurrentTime(new Date());
  }, []);

  const isActive = (path: string) => pathname === path || pathname.startsWith(`${path}/`);
  const signInHref = `/sign-in?redirect_url=${encodeURIComponent(pathname)}`;
  const accountLabel = currentUserQuery.data?.letterboxd_username
    ? `@${currentUserQuery.data.letterboxd_username}`
    : 'Account';

  return (
    <motion.div 
      className="min-h-screen flex flex-col lg:flex-row"
      initial={{ opacity: 0 }}
      animate={{ opacity: isLoaded ? 1 : 0 }}
      transition={{ duration: 0.8, ease: "easeOut" }}
    >
      {/* Sidebar Navigation */}
      <motion.nav 
        className="relative z-50 w-full flex-shrink-0 border-b border-white/10 bg-[#081321]/95 backdrop-blur-xl lg:sticky lg:top-0 lg:h-screen lg:w-72 lg:border-b-0 lg:border-r lg:bg-black/20"
        initial={{ x: -100, opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        transition={{ duration: 0.6, delay: 0.2, ease: "easeOut" }}
      >
        <div className="flex h-full flex-col px-4 py-3 lg:p-6">
          {/* Logo & Branding */}
          <motion.div
            className="flex items-center justify-between lg:mb-8"
            whileHover={{ scale: 1.02 }}
            transition={{ type: "spring", stiffness: 300 }}
          >
            <div className="flex items-center gap-3">
              <div className="relative">
                <motion.div
                className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-cinema-400 to-cinema-600 shadow-glow lg:h-12 lg:w-12"
                animate={{ 
                  boxShadow: [
                    "0 0 20px rgba(229, 81, 0, 0.3)",
                    "0 0 30px rgba(229, 81, 0, 0.5)",
                    "0 0 20px rgba(229, 81, 0, 0.3)"
                  ]
                }}
                transition={{ duration: 3, repeat: Infinity }}
              >
                  <Image
                    src="/icon.svg"
                    alt=""
                    width={48}
                    height={48}
                    className="h-10 w-10 rounded-xl border border-cinema-400/20 lg:h-12 lg:w-12"
                    priority
                  />
                </motion.div>
              </div>
              <div>
                <h1 className="text-xl font-bold text-white text-glow">Spyboxd</h1>
                <p className="hidden text-sm font-medium text-white/60 lg:block">User Analytics</p>
              </div>
            </div>
            <div className="flex items-center gap-2 lg:hidden">
              {isSignedIn ? (
                <SignOutButton redirectUrl="/">
                  <button
                    type="button"
                    className="inline-flex h-10 items-center gap-2 rounded-lg border border-white/10 px-3 text-xs font-semibold text-white/70 hover:border-cinema-400/30 hover:bg-cinema-500/10 hover:text-white"
                  >
                    <LogOut className="h-4 w-4" />
                    Sign out
                  </button>
                </SignOutButton>
              ) : (
                <Link
                  href={signInHref}
                  className="inline-flex h-10 items-center rounded-lg border border-white/10 px-3 text-xs font-semibold text-white/70 hover:border-cinema-400/30 hover:bg-cinema-500/10 hover:text-white"
                >
                  Sign in
                </Link>
              )}
              <button
                type="button"
                onClick={() => setMobileNavOpen((open) => !open)}
                className="grid h-10 w-10 place-items-center rounded-lg border border-white/10 text-white/70 hover:bg-white/5 hover:text-white"
                aria-label={mobileNavOpen ? 'Close navigation' : 'Open navigation'}
                aria-expanded={mobileNavOpen}
              >
                {mobileNavOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
              </button>
            </div>
          </motion.div>

          <div className={`${mobileNavOpen ? 'mt-4 flex' : 'hidden'} min-h-0 flex-1 flex-col lg:mt-0 lg:flex`}>
            {/* System Status */}
            <motion.div
            className="mb-8 p-4 rounded-xl bg-white/5 border border-white/10 backdrop-blur-sm"
            initial={{ y: 20, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ delay: 0.4 }}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm text-white/70">System Status</span>
              <motion.div 
                className="w-2 h-2 bg-green-400 rounded-full"
                animate={{ scale: [1, 1.2, 1] }}
                transition={{ duration: 2, repeat: Infinity }}
              />
            </div>
            <div className="text-xs text-white/50">
              {currentTime?.toLocaleTimeString() ?? ''}
            </div>
            </motion.div>

            {/* Navigation Items */}
            <div className="min-h-0 flex-1 space-y-2 overflow-y-auto overscroll-contain pr-1">
            {NAVIGATION_ITEMS.map((item, index) => {
              const Icon = isActive(item.path) ? item.activeIcon : item.icon;
              return (
                <motion.div
                  key={item.path}
                  initial={{ x: -50, opacity: 0 }}
                  animate={{ x: 0, opacity: 1 }}
                  transition={{ delay: 0.3 + (index * 0.1) }}
                >
                  <Link href={item.path} onClick={() => setMobileNavOpen(false)}>
                    <motion.div
                      className={`
                        relative group flex items-center space-x-4 p-4 rounded-xl transition-all duration-300
                        ${isActive(item.path) 
                          ? 'bg-cinema-500/20 text-cinema-400 border border-cinema-400/30' 
                          : 'text-white/70 hover:text-white hover:bg-white/10 border border-transparent hover:border-white/20'
                        }
                      `}
                      whileHover={{ 
                        scale: 1.02,
                        x: 5
                      }}
                      whileTap={{ scale: 0.98 }}
                      transition={{ type: "spring", stiffness: 400, damping: 17 }}
                    >
                      {/* Active indicator */}
                      {isActive(item.path) && (
                        <motion.div
                          className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-8 bg-cinema-500 rounded-r-full"
                          layoutId="activeIndicator"
                          transition={{ type: "spring", stiffness: 500, damping: 30 }}
                        />
                      )}
                      
                      <Icon className={`w-6 h-6 flex-shrink-0 ${isActive(item.path) ? 'text-cinema-400' : ''}`} />
                      <div className="flex-1">
                        <div className={`font-semibold ${isActive(item.path) ? 'text-cinema-300' : ''}`}>
                          {item.label}
                        </div>
                        <div className="text-xs text-white/50 group-hover:text-white/70 transition-colors">
                          {item.description}
                        </div>
                      </div>
                      
                      {/* Hover glow effect */}
                      <motion.div
                        className="absolute inset-0 bg-gradient-to-r from-cinema-500/0 via-cinema-500/5 to-cinema-500/0 rounded-xl opacity-0 group-hover:opacity-100 transition-opacity duration-300"
                        animate={{ 
                          backgroundPosition: ["0% 0%", "100% 0%"],
                        }}
                        transition={{ 
                          duration: 2, 
                          repeat: Infinity, 
                          ease: "linear",
                          repeatType: "reverse" 
                        }}
                      />
                    </motion.div>
                  </Link>
                </motion.div>
              );
            })}
            </div>

            <div className="mt-5 border-t border-white/10 pt-4 lg:hidden">
              {isSignedIn ? (
                <div className="flex min-w-0 items-center gap-3 text-sm text-white/60">
                  <UserButton />
                  <span className="truncate" title={accountLabel}>{accountLabel}</span>
                </div>
              ) : (
                <Link href={signInHref} className="text-sm font-semibold text-cinema-300 hover:text-cinema-200">Sign in</Link>
              )}
            </div>
          </div>
        </div>
      </motion.nav>

      {/* Main Content */}
      <main className="flex min-w-0 flex-1 flex-col min-h-screen lg:min-h-auto">
        {/* Top Header */}
        <motion.header 
          className="hidden border-b border-white/10 bg-black/10 px-6 py-3 backdrop-blur-md lg:block"
          initial={{ y: -50, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ duration: 0.6, delay: 0.3 }}
        >
          <div className="flex min-h-11 items-center justify-between gap-4">
            {/* Pages render their own heading, so the bar carries utilities
                only: the admin data-scope lens and the account controls. */}
            <AdminScopeToggle />
            <div aria-hidden="true" />
            {isSignedIn ? (
              <div className="flex items-center gap-3">
                <UserButton />
                <span className="max-w-44 truncate text-sm font-semibold text-white/65" title={accountLabel}>
                  {accountLabel}
                </span>
                <SignOutButton redirectUrl="/">
                  <button
                    type="button"
                    className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-white/70 hover:border-cinema-400/30 hover:bg-cinema-500/10 hover:text-white"
                  >
                    <LogOut className="h-4 w-4" />
                    Sign out
                  </button>
                </SignOutButton>
              </div>
            ) : (
              <Link href={signInHref} className="btn-secondary">Sign in</Link>
            )}
          </div>
        </motion.header>

        {/* Page Content with Animation */}
        <div className="flex-1 p-4 sm:p-6">
          <AnimatePresence mode="wait">
            <motion.div
              key={pathname}
              initial={{ opacity: 0, y: 20, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -20, scale: 1.02 }}
              transition={{ 
                duration: 0.4, 
                ease: [0.25, 0.46, 0.45, 0.94] 
              }}
            >
              {children}
            </motion.div>
          </AnimatePresence>
        </div>
      </main>
    </motion.div>
  );
};

export default Layout;
