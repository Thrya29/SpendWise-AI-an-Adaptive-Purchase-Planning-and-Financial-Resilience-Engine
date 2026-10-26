import { defineConfig } from "@playwright/test";

/** Records the walkthrough video and manual screenshots against a running SpendWise. */
export default defineConfig({
  testDir: ".",
  timeout: 15 * 60_000,
  reporter: [["list"]],
  expect: { timeout: 30_000 },
  outputDir: "../test-results/demo",
  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:3000",
    channel: process.env.PW_CHANNEL || undefined,
    viewport: { width: 1280, height: 720 },
    deviceScaleFactor: 1,
    colorScheme: "light",
    actionTimeout: 30_000,
    navigationTimeout: 60_000,
    locale: "en-IN",
    timezoneId: "Asia/Kolkata",
  },
});
