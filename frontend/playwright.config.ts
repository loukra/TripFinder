import { defineConfig, devices } from "@playwright/test";

// This is the one E2E happy path plan §9 asks for. It never talks to a real
// backend — every /api/research* route is intercepted (see e2e/happy-path.spec.ts)
// so the suite stays hermetic, matching the project's "no live network calls
// in the normal test suite" spirit even though plan §9's wording targets the
// backend specifically.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: "list",
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: "npm run dev",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    // A short poll cadence so the happy-path test doesn't sit through
    // production's real 2s interval.
    env: { NEXT_PUBLIC_POLL_INTERVAL_MS: "50" },
  },
});
