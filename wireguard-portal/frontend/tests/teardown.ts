import { existsSync, readFileSync, unlinkSync } from "node:fs";
export default function teardown() {
  const file = process.env.PORTAL_TEST_CREDENTIALS!;
  if (!existsSync(file)) return;
  const fixture = JSON.parse(readFileSync(file, "utf8"));
  if (fixture.pid) process.kill(fixture.pid, "SIGTERM");
  unlinkSync(file);
}
