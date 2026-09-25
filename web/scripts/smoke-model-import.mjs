import { _electron as electron } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const executablePath = path.resolve(process.argv[2] || "desktop/dist/win-unpacked/OmniStage.exe");
const appData = path.resolve(process.argv[3] || "build/model-import-appdata");
const modelPack = path.resolve("desktop/model-pack");
fs.mkdirSync(appData, { recursive: true });
let desktop;
try {
  desktop = await electron.launch({ executablePath,
    env: { ...process.env, OMNISTAGE_USER_DATA: path.join(appData, "OmniStage") },
    timeout: 90_000 });
  const expectedProfile = path.join(appData, "OmniStage");
  const actualProfile = await desktop.evaluate(({ app }) => app.getPath("userData"));
  if (actualProfile !== expectedProfile) throw new Error(`Perfil no aislado: ${actualProfile}`);
  const page = await desktop.firstWindow();
  await page.waitForURL("http://127.0.0.1:8080/admin", { timeout: 90_000 });
  await page.getByRole("heading", { name: "Crear operador inicial" }).waitFor({ timeout: 60_000 });
  await page.getByLabel("Correo electrónico").fill("fixture@example.invalid");
  await page.getByLabel("Contraseña").fill("fixture-only-password");
  await page.getByRole("button", { name: "Crear cuenta" }).click();
  await page.getByRole("heading", { name: "Resumen del evento" }).waitFor({ timeout: 30_000 });
  await desktop.evaluate(({ dialog }, folder) => {
    dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [folder] });
  }, modelPack);
  await page.getByRole("button", { name: "Importar desde una carpeta (sin internet)" }).click();
  await page.getByText("faster-whisper y Gemma 4 E2B instalados y verificados.").waitFor({ timeout: 300_000 });
  const models = path.join(appData, "OmniStage", "models");
  if (!fs.existsSync(path.join(models, "gemma-4-e2b-q4.gguf")) ||
      !fs.existsSync(path.join(models, "faster-whisper", "model.bin"))) {
    throw new Error("Modelos no fueron importados al perfil aislado");
  }
  console.log(JSON.stringify({ modelPack, models, imported: true }));
} finally {
  if (desktop) await desktop.close();
}
