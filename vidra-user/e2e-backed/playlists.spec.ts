import { expect, test } from "@playwright/test";

import { seedPublishedChannel, uniqueId } from "./fixtures";

// Proves the playlist round trip against a real vidra-core + PostgreSQL: a viewer
// creates a playlist and adds a video from the watch page, the video then appears
// on the playlist detail page after a fresh refetch, and removing it persists.
// DB evidence (the playlist_items row) is captured separately via psql.
test("create a playlist, add a video from the watch page, then remove it", async ({
  page,
  request,
}) => {
  const { videoTitle } = await seedPublishedChannel(request);

  // A fresh viewer signs up (the session lives in memory).
  const id = uniqueId();
  await page.goto("/signup");
  await page.getByLabel("Username").fill(`fan${id}`);
  await page.getByLabel("Email").fill(`e2e-fan-${id}@example.test`);
  await page.getByLabel("Password").fill("supersecret-e2e");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  // Open the seeded video's watch page (client-side nav so the session survives).
  await page.getByRole("heading", { name: videoTitle }).click();
  await expect(page.getByRole("heading", { level: 1, name: videoTitle })).toBeVisible();

  // Create a playlist AND add this video in one go via "Save to playlist".
  await page.getByRole("button", { name: "Save to playlist" }).click();
  await page.getByLabel("New playlist name").fill("My Mix");
  const created = page.waitForResponse(
    (r) => /\/api\/v1\/playlists$/.test(r.url()) && r.request().method() === "POST" && r.ok(),
  );
  const added = page.waitForResponse(
    (r) => /\/playlists\/[^/]+\/videos$/.test(r.url()) && r.request().method() === "POST" && r.ok(),
  );
  await page.getByRole("button", { name: "Create" }).click();
  await created;
  await added;

  // The playlist now contains the video (a fresh detail fetch from the backend).
  await page.getByRole("link", { name: "Playlists" }).click();
  await page.getByRole("link", { name: /My Mix/ }).click();
  await expect(page.getByRole("heading", { name: videoTitle })).toBeVisible();

  // Removing it persists: gone after navigating away and back.
  const removed = page.waitForResponse(
    (r) => /\/videos\/[^/]+$/.test(r.url()) && r.request().method() === "DELETE" && r.ok(),
  );
  await page.getByRole("button", { name: `Remove ${videoTitle} from playlist` }).click();
  await removed;
  await page.getByRole("link", { name: "Playlists" }).click();
  await page.getByRole("link", { name: /My Mix/ }).click();
  await expect(page.getByText("This playlist is empty")).toBeVisible();
});
