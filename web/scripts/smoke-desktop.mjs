import { _electron as electron } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const executablePath = path.resolve(process.argv[2] || "desktop/dist/win-unpacked/OmniStage.exe");
const appData = path.resolve(process.argv[3] || "build/desktop-smoke-appdata");
fs.mkdirSync(appData, { recursive: true });
let desktop;
try {
  desktop = await electron.launch({
    executablePath,
    env: { ...process.env, OMNISTAGE_USER_DATA: path.join(appData, "OmniStage") },
    timeout: 90_000,
  });
  const expectedProfile = path.join(appData, "OmniStage");
  const actualProfile = await desktop.evaluate(({ app }) => app.getPath("userData"));
  if (actualProfile !== expectedProfile) throw new Error(`Perfil no aislado: ${actualProfile}`);
  const page = await desktop.firstWindow();
  await page.waitForURL("http://127.0.0.1:8080/admin", { timeout: 90_000 });
  const internal = await fetch("http://127.0.0.1:8080/healthz");
  const publicHealth = await fetch("http://127.0.0.1:8088/healthz");
  const operatorOnPublic = await fetch("http://127.0.0.1:8088/api/operator/me");
  if (!internal.ok || !publicHealth.ok || operatorOnPublic.status !== 404) {
    throw new Error(`Bad origins: ${internal.status}, ${publicHealth.status}, ${operatorOnPublic.status}`);
  }
  console.log(JSON.stringify({ executablePath, appData, internal: internal.status,
    public: publicHealth.status, operatorOnPublic: operatorOnPublic.status }));
} finally {
  if (desktop) await desktop.close();
}
