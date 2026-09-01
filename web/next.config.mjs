/** @type {import('next').NextConfig} */
const nextConfig = {
  // Static export: the FastAPI backend serves web/out directly, so `python
  // main.py` brings up the dashboard with no Node process in the loop.
  output: "export",
  distDir: "out",
  images: { unoptimized: true },
  trailingSlash: true,
};

export default nextConfig;
