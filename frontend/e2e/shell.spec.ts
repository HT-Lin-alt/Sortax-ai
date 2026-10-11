import { expect, test } from "@playwright/test";

test("renders the F0 mobile shell", async ({ page }) => {
  await page.route("**/health/live", async (route) => {
    await route.fulfill({ json: { status: "ok" } });
  });
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Sortax" })).toBeVisible();
  await expect(page.getByText("Service available")).toBeVisible();
  await expect(page.getByLabel("Message Sortax")).toBeDisabled();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
  ).toBe(true);
});
