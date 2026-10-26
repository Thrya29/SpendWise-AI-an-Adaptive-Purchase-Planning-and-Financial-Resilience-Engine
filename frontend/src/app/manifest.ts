import type { MetadataRoute } from "next";

/** Lets people install SpendWise on a phone's home screen. Data is always live, never cached. */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "SpendWise AI",
    short_name: "SpendWise",
    description: "Plan purchases against real cash flow and stay safe through salary delays.",
    start_url: "/dashboard",
    scope: "/",
    display: "standalone",
    background_color: "#f7f8fa",
    theme_color: "#0f766e",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
