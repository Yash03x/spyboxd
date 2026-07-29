import type { NextConfig } from 'next';
import path from 'node:path';

const nextConfig: NextConfig = {
  outputFileTracingRoot: path.resolve(__dirname),
  images: {
    remotePatterns: [
      { hostname: 'a.ltrbxd.com' },
      { hostname: 'image.tmdb.org' },
    ],
  },
};

export default nextConfig;
