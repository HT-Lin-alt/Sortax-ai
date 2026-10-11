import { spawn } from "node:child_process";
import { join } from "node:path";

const server = spawn(process.execPath, [join("scripts", "static-server.mjs")], {
  stdio: "ignore",
  windowsHide: true,
});

try {
  await waitForServer("http://127.0.0.1:4173/");
  const playwright = spawn(
    process.execPath,
    [join("node_modules", "@playwright", "test", "cli.js"), "test", ...process.argv.slice(2)],
    { stdio: "inherit", windowsHide: true },
  );
  const exitCode = await new Promise((resolve, reject) => {
    playwright.once("error", reject);
    playwright.once("exit", (code) => resolve(code ?? 1));
  });
  process.exitCode = exitCode;
} finally {
  server.kill();
}

async function waitForServer(url) {
  const deadline = Date.now() + 10_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) {
        return;
      }
    } catch {
      // The server is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error("Frontend test server did not start within 10 seconds");
}
