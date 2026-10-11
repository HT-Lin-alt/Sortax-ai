import { expect, test } from "@playwright/test";

test("renders the complete F1 fixture timeline", async ({ page }) => {
  await page.route("**/health/live", async (route) => {
    await route.fulfill({ json: { status: "ok" } });
  });
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Sortax" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "A few details first" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Documents to gather" })).toBeAttached();
  await expect(page.getByRole("heading", { name: "Tax information summary" })).toBeAttached();
  await expect(page.getByLabel("Message Sortax")).toBeDisabled();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
  ).toBe(true);
});

for (const viewport of [
  { width: 390, height: 844 },
  { width: 430, height: 932 },
  { width: 484, height: 1024 },
]) {
  test(`matches the ${String(viewport.width)}x${String(viewport.height)} visual baseline`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.route("**/health/live", async (route) => {
      await route.fulfill({ json: { status: "ok" } });
    });
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Sortax" })).toBeVisible();
    await expect(page).toHaveScreenshot(`f1-${String(viewport.width)}x${String(viewport.height)}.png`, {
      animations: "disabled",
      caret: "hide",
      fullPage: true,
    });
  });
}
