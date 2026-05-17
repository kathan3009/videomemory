/** @type {import('next').NextConfig} */
const apiBase = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

const nextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${apiBase}/:path*` },
    ];
  },
};

export default nextConfig;
