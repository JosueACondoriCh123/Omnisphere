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
  const firstUrl = page.url();
  if (firstUrl.startsWith("file:")) {
    await page.getByRole("heading", { name: "OMNISTAGE" }).waitFor({ timeout: 10_000 });
  }
  await page.waitForURL("http://127.0.0.1:8080/admin", { timeout: 90_000 });
  const internal = await fetch("http://127.0.0.1:8080/healthz");
  const publicHealth = await fetch("http://127.0.0.1:8088/healthz");
  const operatorOnPublic = await fetch("http://127.0.0.1:8088/api/operator/me");
  if (!internal.ok || !publicHealth.ok || operatorOnPublic.status !== 404) {
    throw new Error(`Bad origins: ${internal.status}, ${publicHealth.status}, ${operatorOnPublic.status}`);
  }
  await page.getByRole("heading", { name: "Crear operador inicial" }).waitFor({ timeout: 30_000 });
  await page.getByLabel("Correo electrónico").fill("fixture@example.invalid");
  await page.getByLabel("Contraseña").fill("fixture-only-password");
  await page.getByRole("button", { name: "Crear cuenta" }).click();
  await page.getByRole("navigation", { name: "Operación" }).getByRole("link", { name: /Modelos locales/ }).click();
  await page.getByRole("heading", { name: "Modelos listos para operar" }).waitFor({ timeout: 30_000 });
  if (!(await page.getByRole("button", { name: "Ejecutar prueba" }).isDisabled())) {
    throw new Error("La prueba local debería estar bloqueada sin Gemma");
  }
  await page.screenshot({ path: path.join(appData, "modelos-locales.png"), fullPage: true });
  console.log(JSON.stringify({ executablePath, appData, internal: internal.status,
    public: publicHealth.status, operatorOnPublic: operatorOnPublic.status,
    splashSeen: firstUrl.startsWith("file:"), modelConsole: true }));
} finally {
  if (desktop) await desktop.close();
}
