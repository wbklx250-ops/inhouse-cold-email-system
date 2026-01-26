/** @type {import('next').NextConfig} */
const nextConfig = {
  // Enable standalone output for Docker deployment
  output: 'standalone',
  
  // Environment variables available to the client
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
  },
  
  // Configure external packages that need to be bundled
  serverExternalPackages: [],
  
  // Image optimization (use unoptimized if you have issues)
  images: {
    unoptimized: process.env.NODE_ENV === 'development',
    domains: [],
  },
  
  // API rewrites to backend (useful for development)
  async rewrites() {
    return process.env.NODE_ENV === 'development'
      ? [
          {
            source: '/api/v1/:path*',
            destination: `${process.env.NEXT_PUBLIC_API_URL}/api/v1/:path*`,
          },
        ]
      : [];
  },
  
  // CORS headers if needed
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'X-Content-Type-Options', value: 'nosniff' },
        ],
      },
    ];
  },
};

module.exports = nextConfig;
