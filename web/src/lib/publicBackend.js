export const isPublicDeployment = import.meta.env.MODE === "vercel";

const configuredApiOrigin = import.meta.env.VITE_PUBLIC_API_ORIGIN?.trim() || "";
const configuredWsOrigin = import.meta.env.VITE_PUBLIC_WS_ORIGIN?.trim() || "";

export const hasLiveBackend = !isPublicDeployment || Boolean(configuredApiOrigin);

export function publicApiUrl(path) {
  if (!configuredApiOrigin) return path;
  return new URL(path, `${configuredApiOrigin.replace(/\/+$/, "")}/`).toString();
}

export function publicSocketUrl(path) {
  const origin = configuredWsOrigin || configuredApiOrigin;
  if (origin) {
    const url = new URL(path, `${origin.replace(/\/+$/, "")}/`);
    url.protocol = ["https:", "wss:"].includes(url.protocol) ? "wss:" : "ws:";
    return url.toString();
  }
  const proto = globalThis.location?.protocol === "https:" ? "wss:" : "ws:";
  const host = globalThis.location?.host || "localhost";
  return `${proto}//${host}${path}`;
}
