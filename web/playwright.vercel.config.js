import { defineConfig } from "@playwright/test";
import base from "./playwright.config.js";

export default defineConfig({
  ...base,
  testDir: "./vercel-e2e",
});
