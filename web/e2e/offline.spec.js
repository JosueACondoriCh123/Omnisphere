import { expect, test } from "@playwright/test";

test("offline reload still opens the app shell", async ({ page, context }) => {
  await page.goto("/app");
  await page.evaluate(async () => {
    const ready = navigator.serviceWorker.ready;
    await ready;
  });
  if (!(await page.evaluate(() => navigator.serviceWorker.controller))) {
    await page.reload();
    await page.evaluate(() => navigator.serviceWorker.ready);
  }
  await context.setOffline(true);
  await page.reload();
  await expect(
    page.getByText("Sin conexión; los subtítulos en vivo están pausados"),
  ).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Sala" })).toBeVisible();
});
