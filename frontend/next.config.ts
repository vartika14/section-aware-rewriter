import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Next regenerates AGENTS.md / CLAUDE.md on every dev start; they are scaffold
  // noise in a repo meant to be read by a reviewer.
  agentRules: false,
};

export default nextConfig;
