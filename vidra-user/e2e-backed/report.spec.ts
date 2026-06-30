import { expect, test } from "@playwright/test";

import { adminToken, reportsQueue, seedComment, seedPublishedChannel, uniqueId } from "./fixtures";

// Signs up a fresh viewer in the UI (the session lives in memory, so subsequent
// navigation is client-side).
async function signUpViewer(page: import("@playwright/test").Page, id: string) {
  await page.goto("/signup");
  await page.getByLabel("Username").fill(`fan${id}`);
  await page.getByLabel("Email").fill(`e2e-fan-${id}@example.test`);
  await page.getByLabel("Password").fill("supersecret-e2e");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

// Proves the video-report round trip against a real vidra-core + PostgreSQL: a
// viewer files a report from the watch page; it is then read back from the admin
// moderation queue (as the deterministic admin), proving the row persisted.
test("reporting a video from the watch page persists to the moderation queue", async ({
  page,
  request,
}) => {
  const { videoTitle } = await seedPublishedChannel(request);
  const id = uniqueId();
  const reason = `vid-report-${id}`;

  await signUpViewer(page, id);

  // Reach the seeded video's watch page from the home feed (client-side nav).
  await page.getByRole("heading", { name: videoTitle }).click();
  await expect(page.getByRole("heading", { level: 1, name: videoTitle })).toBeVisible();

  await page.getByRole("button", { name: "Report this video" }).click();
  const dialog = page.getByRole("dialog", { name: "Report this video" });
  await dialog.getByLabel("Reason for report").fill(reason);
  const reported = page.waitForResponse(
    (r) => /\/videos\/[^/]+\/report$/.test(r.url()) && r.request().method() === "POST" && r.ok(),
  );
  await dialog.getByRole("button", { name: "Submit report" }).click();
  await reported;
  await expect(page.getByText("your report has been sent to the moderators")).toBeVisible();

  // Persisted: the report shows up in the admin moderation queue (read as admin).
  const token = await adminToken(request);
  const mine = (await reportsQueue(request, token)).find((r) => r.reason === reason);
  expect(mine).toBeTruthy();
  expect(mine?.target_type).toBe("video");
  expect(mine?.status).toBe("open");
});

// Proves the comment-report round trip: the channel owner seeds a comment, a
// different viewer reports it from the watch page, and it appears in the queue.
test("reporting a comment from the watch page persists to the moderation queue", async ({
  page,
  request,
}) => {
  const { videoId, videoTitle, token: ownerToken } = await seedPublishedChannel(request);
  const id = uniqueId();
  const reason = `cmt-report-${id}`;
  const commentBody = `seeded comment ${id}`;
  await seedComment(request, videoId, ownerToken, commentBody);

  await signUpViewer(page, id);

  await page.getByRole("heading", { name: videoTitle }).click();
  await expect(page.getByText(commentBody)).toBeVisible();

  await page.getByRole("button", { name: "Report this comment" }).click();
  const dialog = page.getByRole("dialog", { name: "Report this comment" });
  await dialog.getByLabel("Reason for report").fill(reason);
  const reported = page.waitForResponse(
    (r) => /\/comments\/[^/]+\/report$/.test(r.url()) && r.request().method() === "POST" && r.ok(),
  );
  await dialog.getByRole("button", { name: "Submit report" }).click();
  await reported;
  await expect(page.getByText("your report has been sent to the moderators")).toBeVisible();

  // Persisted: the comment report shows up in the admin moderation queue.
  const token = await adminToken(request);
  const mine = (await reportsQueue(request, token)).find((r) => r.reason === reason);
  expect(mine).toBeTruthy();
  expect(mine?.target_type).toBe("comment");
});
