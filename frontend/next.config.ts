import type { NextConfig } from 'next';
import path from 'node:path';

const nextConfig: NextConfig = {
  outputFileTracingRoot: path.resolve(__dirname),
  // The redesign renames the feature-named destinations to question-named
  // sections. The old paths are in people's history and their bookmarks, so
  // they redirect rather than 404. Query strings are preserved by default, which
  // is what carries a profile selection through the move.
  async redirects() {
    return [
      { source: '/dashboard', destination: '/overview', permanent: true },
      { source: '/spy-signals', destination: '/overlaps', permanent: true },
      { source: '/analysis', destination: '/people?tab=one', permanent: true },
      { source: '/compare', destination: '/people?tab=two', permanent: true },
      { source: '/network', destination: '/people?tab=circle', permanent: true },
      { source: '/watch-together', destination: '/tonight', permanent: true },
    ];
  },
  images: {
    remotePatterns: [
      { hostname: 'a.ltrbxd.com' },
      { hostname: 'image.tmdb.org' },
    ],
  },
};

export default nextConfig;
