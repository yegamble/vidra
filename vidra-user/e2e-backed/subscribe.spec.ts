import { expect, test } from "@playwright/test";

import { followerCount, seedPublishedChannel, uniqueId } from "./fixtures";

// Backend-backed e2e (real vidra-core + Postgres, no mocks): proves the subscribe
// data-mutating flow persists. We seed (via the API) a channel with a published
// video, then in the UI a fresh viewer signs up, reaches the channel page by
// clicking the video card's channel link (client-side nav keeps the session), and
// subscribes — and the channel's follower_count goes 0 → 1 in the database.
test("subscribing from a video card persists the follow", async ({ page, request }) => {
  const { handle, displayName } = await seedPublishedChannel(request);
  expect(await followerCount(request, handle)).toBe(0);

  // A fresh viewer signs up (the signup form redirects to the home feed).
  const id = uniqueId();
  await page.goto("/signup");
  await page.getByLabel("Username").fill(`fan${id}`);
  await page.getByLabel("Email").fill(`e2e-fan-${id}@example.test`);
  await page.getByLabel("Password").fill("supersecret-e2e");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  // The seeded video is the newest, so it's on the home feed; click its channel
  // link to reach the channel page (client-side nav preserves the session).
  await page.getByRole("link", { name: displayName }).click();
  await expect(page.getByRole("heading", { name: displayName })).toBeVisible();

  // Subscribe, then prove the follow persisted in the database.
  await page.getByRole("button", { name: "Subscribe" }).click();
  await expect(page.getByRole("button", { name: "Subscribed" })).toBeVisible();
  expect(await followerCount(request, handle)).toBe(1);
});
