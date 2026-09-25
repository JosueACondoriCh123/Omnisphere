/** @vitest-environment jsdom */

import "@testing-library/jest-dom/vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import "../index.css";
import App from "./App.jsx";
import Overlay from "./Overlay.jsx";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

test("app mock solidifies the same draft node into a commit", () => {
  render(
    <MemoryRouter initialEntries={["/app?mock=1"]}>
      <App />
    </MemoryRouter>,
  );

  act(() => vi.advanceTimersByTime(200));
  const draft = screen.getByRole("listitem");
  expect(draft).toHaveAttribute("data-state", "draft");

  act(() => vi.advanceTimersByTime(2900));
  const committed = screen.getByRole("listitem");
  expect(committed).toBe(draft);
  expect(committed).toHaveAttribute("data-state", "committed");
  console.log("APP_OK draft_to_commit_solidified=1");
});

test("overlay mock keeps a transparent canvas and safe margins", () => {
  render(
    <MemoryRouter initialEntries={["/overlay/1?mock=1&theme=obs&lang=es&size=md"]}>
      <Routes>
        <Route path="/overlay/:stageId" element={<Overlay />} />
      </Routes>
    </MemoryRouter>,
  );

  act(() => vi.advanceTimersByTime(200));
  expect(document.documentElement.dataset.surface).toBe("overlay");
  expect(screen.getByRole("main")).toHaveAttribute("data-transparent", "true");
  expect(document.querySelector(".lower-third")).toHaveAttribute("data-safe", "1");
  const background = getComputedStyle(document.documentElement).backgroundColor;
  expect(["transparent", "rgba(0, 0, 0, 0)", ""]).toContain(background);
  console.log("OVERLAY_OK transparent=1 safe_margins=1");
});
