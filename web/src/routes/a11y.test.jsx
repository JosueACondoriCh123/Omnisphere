/** @vitest-environment jsdom */

import "@testing-library/jest-dom/vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import App from "./App.jsx";
import { statusLabel } from "../lib/status.js";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

function renderApp() {
  return render(
    <MemoryRouter initialEntries={["/app?mock=1"]}>
      <App />
    </MemoryRouter>,
  );
}

test("audience controls expose accessible names and accept keyboard focus", () => {
  renderApp();
  const controls = [
    screen.getByRole("combobox", { name: "Sala" }),
    screen.getByRole("combobox", { name: "Idioma" }),
    screen.getByRole("combobox", { name: "Tamaño" }),
    screen.getByRole("checkbox", { name: "Alto contraste" }),
  ];

  for (const control of controls) {
    expect(control.tabIndex).toBeGreaterThanOrEqual(0);
    control.focus();
    expect(control).toHaveFocus();
  }

  expect(screen.getByRole("status")).toHaveTextContent("demo");
});

test("screen reader announces each commit once and ignores changing drafts", () => {
  renderApp();
  const live = screen.getByTestId("commit-announcer");
  expect(live).toHaveAttribute("aria-live", "polite");

  act(() => vi.advanceTimersByTime(220));
  expect(screen.getByRole("listitem")).toHaveAttribute("data-state", "draft");
  expect(live).toHaveTextContent("");

  act(() => vi.advanceTimersByTime(300));
  expect(screen.getByRole("listitem")).toHaveAttribute("data-state", "draft");
  expect(live).toHaveTextContent("");

  act(() => vi.advanceTimersByTime(3200));
  const committed = screen.getByRole("listitem");
  expect(committed).toHaveAttribute("data-state", "committed");
  expect(live).toHaveTextContent(committed.textContent);

  const announced = live.textContent;
  act(() => vi.advanceTimersByTime(1000));
  expect(live).toHaveTextContent(announced);
});

test("connection states name connecting, reconnecting, a missing backend, and a stopped stream", () => {
  const phrases = ["connecting", "reconnecting", "error", "stopped"].map(statusLabel);
  render(
    <div>
      {phrases.map((phrase) => (
        <p key={phrase} role="status">
          {phrase}
        </p>
      ))}
    </div>,
  );
  expect(screen.getByText("conectando")).toBeInTheDocument();
  expect(screen.getByText("reconectando")).toBeInTheDocument();
  expect(screen.getByText("backend no disponible")).toBeInTheDocument();
  expect(screen.getByText("stream detenido")).toBeInTheDocument();
});

test("going offline keeps the committed caption and says live captions are paused", () => {
  renderApp();
  act(() => vi.advanceTimersByTime(3200));
  const committed = screen.getByRole("listitem");
  expect(committed).toHaveAttribute("data-state", "committed");
  const text = committed.textContent;

  act(() => {
    window.dispatchEvent(new Event("offline"));
  });

  expect(
    screen.getByText("Sin conexión; los subtítulos en vivo están pausados"),
  ).toBeInTheDocument();
  expect(screen.getByRole("listitem")).toHaveTextContent(text);
  expect(screen.getByRole("listitem")).toHaveAttribute("data-state", "committed");
});
