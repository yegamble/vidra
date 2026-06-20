import { expect, test } from "@playwright/test";

test("home page renders the Vidra heading", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Vidra" })).toBeVisible();
});
