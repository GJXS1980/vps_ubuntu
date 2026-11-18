import { defineConfig } from "@playwright/test";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { randomUUID } from "node:crypto";
process.env.PORTAL_TEST_CREDENTIALS ||= join(
  tmpdir(),
  "portal-e2e-" + randomUUID() + ".json",
);
const origin = "https://127.0.0.1:" + (process.env.PORTAL_TEST_PORT || "17444");
export default defineConfig({
  globalTeardown: "./tests/teardown.ts",
  testDir: "./tests",
  workers: 1,
  use: {
    baseURL: origin,
    ignoreHTTPSErrors: true,
    launchOptions: { executablePath: process.env.PORTAL_CHROME || undefined },
  },
  webServer: {
    command:
      process.env.PORTAL_BROWSER_SERVER ||
      "python ../backend/tests/browser_server.py dist",
    url: origin + "/api/health",
    ignoreHTTPSErrors: true,
    reuseExistingServer: false,
    timeout: 60000,
  },
});
