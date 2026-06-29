import { expect, test } from "@playwright/test";

import { seedPublishedChannel, uniqueId } from "./fixtures";

// Proves the watch-history round trip against a real vidra-core + PostgreSQL: a
// signed-in viewer plays a video (the watch page records progress), the video
// then appears in their history after a fresh authed refetch, and removing it
// persists (it is gone after navigating away and back). DB evidence (the
// watch_history row) is captured separately via psql.
test("watching a video records it to history and removing it persists", async ({
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

  // Reach the seeded video's watch page from the home feed (client-side nav so
  // the in-memory session survives).
  await page.getByRole("heading", { name: videoTitle }).click();
  await expect(page.getByRole("heading", { level: 1, name: videoTitle })).toBeVisible();

  // Drive playback so the watch page reports progress (the PUT that enters the
  // video into the viewer's history). Wait for that write before refetching.
  const recorded = page.waitForResponse(
    (r) => r.url().includes("/watch-progress") && r.request().method() === "PUT" && r.ok(),
  );
  await page.evaluate(async () => {
    const v = document.querySelector("video");
    if (!v) return;
    v.muted = true;
    try {
      await v.play();
    } catch {
      // Autoplay may be blocked; the synthetic timeupdate below still records.
    }
    v.dispatchEvent(new Event("timeupdate"));
  });
  await recorded;

  // The video appears in the history list (a fresh authed GET /me/history).
  await page.getByRole("link", { name: "History" }).click();
  await expect(page.getByRole("heading", { name: videoTitle })).toBeVisible();

  // Removing the entry persists: gone after navigating away and back.
  const removed = page.waitForResponse(
    (r) => /\/me\/history\//.test(r.url()) && r.request().method() === "DELETE" && r.ok(),
  );
  await page.getByRole("button", { name: `Remove ${videoTitle} from history` }).click();
  await removed;
  await page.getByRole("link", { name: "Home" }).click();
  await page.getByRole("link", { name: "History" }).click();
  await expect(page.getByText("No watch history yet")).toBeVisible();
});
