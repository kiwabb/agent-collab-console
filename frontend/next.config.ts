import type { NextConfig } from "next";

const backendApiBase = process.env.BACKEND_API_BASE ?? "http://localhost:9000";

const nextConfig: NextConfig = {
  eslint: {
    ignoreDuringBuilds: true,
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendApiBase}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
