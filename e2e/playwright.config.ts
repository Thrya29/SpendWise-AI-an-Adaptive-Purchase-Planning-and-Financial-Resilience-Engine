import { defineConfig, devices } from "@playwright/test";

/**
 * BASE_URL defaults to the Docker Compose web port. Set PW_CHANNEL=chrome to use an installed
 * Chrome instead of the bundled Chromium (handy on machines without the download).
 */
export default defineConfig({
  testDir: "tests",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "phone",
      use: {
        ...devices["Pixel 7"],
        channel: process.env.PW_CHANNEL || undefined,
      },
    },
  ],
});
