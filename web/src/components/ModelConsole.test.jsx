/** @vitest-environment jsdom */

import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import ModelConsole from "./ModelConsole.jsx";

afterEach(cleanup);

test("el operador puede arrancar Gemma y ejecutar una traducción local", async () => {
  const desktop = {
    setupStatus: vi.fn().mockResolvedValue({ modelDownload: { phase: "idle" } }),
    onModelProgress: vi.fn().mockReturnValue(() => {}),
    startLocalModels: vi.fn().mockResolvedValue({ starting: true }),
    testLocalModel: vi.fn().mockResolvedValue("Hello"),
  };
  render(<MemoryRouter><ModelConsole desktop={desktop}
    status={{ models: { asr: true, gemma: true }, services: { backend: true, gemma: true } }}
    provider={{ mode: "auto" }} onMode={vi.fn()} onChanged={vi.fn().mockResolvedValue()} /></MemoryRouter>);

  fireEvent.click(screen.getByRole("button", { name: "Reiniciar Gemma" }));
  await waitFor(() => expect(desktop.startLocalModels).toHaveBeenCalledOnce());
  fireEvent.change(screen.getByPlaceholderText("Escribí una frase corta…"), { target: { value: "Hola" } });
  fireEvent.click(screen.getByRole("button", { name: "Ejecutar prueba" }));
  await waitFor(() => expect(screen.getByText("Hello")).toBeInTheDocument());
  expect(desktop.testLocalModel).toHaveBeenCalledWith("Hola", "en");
});

test("sin modelos ofrece importación y no permite ejecutar una prueba", () => {
  render(<MemoryRouter><ModelConsole desktop={null} status={{ models: { asr: false, gemma: false }, services: {} }}
    provider={{ mode: "auto" }} onMode={vi.fn()} onChanged={vi.fn()} /></MemoryRouter>);
  expect(screen.getByRole("button", { name: "Importar carpeta de modelos" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Ejecutar prueba" })).toBeDisabled();
});
