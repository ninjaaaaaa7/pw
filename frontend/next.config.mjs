/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Static export: the FastAPI backend serves the built files in production,
  // so one container hosts both API and UI.
  output: "export",
  images: { unoptimized: true },
};

export default nextConfig;
