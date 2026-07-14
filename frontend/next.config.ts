import type { NextConfig } from "next";
import path from "node:path";

const backendApiBase = process.env["BACKEND_API_BASE"] ?? "http://127.0.0.1:9000";

const nextConfig: NextConfig = {
  outputFileTracingRoot: path.resolve(),
  distDir: process.env["NEXT_DIST_DIR"] ?? ".next",
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
