import { afterEach, expect, test, vi } from "vitest";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

test("public API and caption socket use the configured HTTPS origin", async () => {
  vi.stubEnv("VITE_PUBLIC_API_ORIGIN", "https://captions.example.org/");
  vi.resetModules();
  const { publicApiUrl, publicSocketUrl } = await import("./publicBackend.js");
  expect(publicApiUrl("/api/stages")).toBe("https://captions.example.org/api/stages");
  expect(publicSocketUrl("/ws/stages/1/es")).toBe("wss://captions.example.org/ws/stages/1/es");
});

test("a separate WSS origin keeps the secure socket protocol", async () => {
  vi.stubEnv("VITE_PUBLIC_API_ORIGIN", "https://captions.example.org");
  vi.stubEnv("VITE_PUBLIC_WS_ORIGIN", "wss://streams.example.org");
  vi.resetModules();
  const { publicSocketUrl } = await import("./publicBackend.js");
  expect(publicSocketUrl("/ws/stages/2/en")).toBe("wss://streams.example.org/ws/stages/2/en");
});
