export function statusLabel(status) {
  switch (status) {
    case "connecting":
      return "conectando";
    case "reconnecting":
      return "reconectando";
    case "error":
      return "backend no disponible";
    case "stopped":
      return "stream detenido";
    case "open":
      return "en vivo";
    case "mock":
      return "demo";
    case "unavailable":
      return "transmisión aún no disponible";
    default:
      return "conectando";
  }
}
