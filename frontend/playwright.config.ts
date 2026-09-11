import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  timeout: 60_000,
  retries: 0,
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "desktop",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 1050 },
      },
      testIgnore: /mobile\.spec\.ts/,
    },
    {
      name: "mobile",
      use: { ...devices["iPhone 13"], defaultBrowserType: "chromium" },
      testMatch: [
        /mobile\.spec\.ts/,
        /login\.spec\.ts/,
        /catalog\.spec\.ts/,
        /demo-workflow\.spec\.ts/,
        /selection\.spec\.ts/,
        /showcase\.spec\.ts/,
        /execution\.spec\.ts/,
      ],
    },
  ],
});
