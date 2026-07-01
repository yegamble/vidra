import { expect, test, type Page } from "@playwright/test";

// Mocked studio coverage (a real backend is not running in `npm run ci`; the
// publish/edit/delete round-trips are proven in e2e-backed/studio.spec.ts).
const LOGIN = /\/api\/v1\/auth\/login$/;
const FEED = /\/api\/v1\/videos(\?|$)/;
const UNREAD = /\/api\/v1\/me\/notifications\/unread-count$/;
const MY_CHANNELS = /\/api\/v1\/me\/channels$/;
const CREATE_CHANNEL = /\/api\/v1\/channels$/;
const CHANNEL_VIDEOS = /\/api\/v1\/channels\/ada_makes\/videos$/;
const UPLOAD = /\/api\/v1\/videos\/v1\/file$/;
const VIDEO = /\/api\/v1\/videos\/v1$/;
const CAPTIONS = /\/api\/v1\/videos\/v1\/captions$/;
const CAPTION_LANG = /\/api\/v1\/videos\/v1\/captions\/[^/]+$/;
const VIDEO_CONFIG = /\/api\/v1\/videos\/config$/;

function videoConfig() {
  return {
    categories: [
      { id: "1", label: "Music" },
      { id: "7", label: "Gaming" },
    ],
    licenses: [
      { id: "1", label: "Attribution (CC BY)" },
      { id: "7", label: "Public Domain Dedication (CC0)" },
    ],
    languages: [
      { id: "en", label: "English" },
      { id: "fr", label: "French" },
    ],
    privacies: [
      { id: "public", label: "Public" },
      { id: "unlisted", label: "Unlisted" },
      { id: "private", label: "Private" },
    ],
  };
}

function channel(handle: string, name: string) {
  return {
    id: "c1",
    owner_id: "u1",
    handle,
    display_name: name,
    description: "",
    follower_count: 0,
    created_at: new Date().toISOString(),
  };
}

function video(overrides: Record<string, unknown> = {}) {
  return {
    id: "v1",
    channel_id: "c1",
    title: "My clip",
    description: "",
    privacy: "public",
    state: "published",
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

const session = {
  token: "acc",
  refresh_token: "ref",
  token_type: "Bearer",
  expires_in: 900,
  user: {
    id: "u1",
    username: "ada",
    email: "ada@example.test",
    role: "user",
    email_verified: false,
    display_name: "Ada",
    bio: "",
    created_at: new Date().toISOString(),
  },
};

async function signIn(page: Page) {
  await page.route(LOGIN, (route) => route.fulfill({ json: session }));
  await page.route(FEED, (route) =>
    route.fulfill({ json: { videos: [], sort: "recent", limit: 20, offset: 0 } }),
  );
  await page.route(UNREAD, (route) => route.fulfill({ json: { unread_count: 0 } }));
  await page.goto("/login");
  await page.getByLabel("Email").fill("ada@example.test");
  await page.getByLabel("Password").fill("supersecret");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

test("the studio prompts anonymous viewers to sign in", async ({ page }) => {
  await page.goto("/studio");
  await expect(page.getByText("Sign in to use the studio")).toBeVisible();
});

test("a creator can create a channel", async ({ page }) => {
  await signIn(page);
  await page.route(MY_CHANNELS, (route) => route.fulfill({ json: { channels: [] } }));
  await page.route(CREATE_CHANNEL, (route) => {
    if (route.request().method() === "POST") return route.fulfill({ json: channel("ada_makes", "Ada Makes") });
    return route.fulfill({ json: { channels: [] } });
  });
  // The new "Your videos" section loads the new channel's (empty) video list.
  await page.route(CHANNEL_VIDEOS, (route) => route.fulfill({ json: { videos: [] } }));

  await page.getByRole("link", { name: "Studio" }).click();
  await expect(page.getByText("Create your first channel to start publishing.")).toBeVisible();
  await page.getByLabel("Channel handle").fill("ada_makes");
  await page.getByLabel("Channel display name").fill("Ada Makes");
  await page.getByRole("button", { name: "Create channel" }).click();

  // The new channel appears, and the upload form becomes available.
  await expect(page.getByRole("link", { name: /Ada Makes/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Upload a video" })).toBeVisible();
  await expect(page.getByText("No videos in this channel yet.")).toBeVisible();
});

test("a creator can upload and publish a video", async ({ page }) => {
  await signIn(page);
  await page.route(MY_CHANNELS, (route) =>
    route.fulfill({ json: { channels: [channel("ada_makes", "Ada Makes")] } }),
  );
  // GET lists the channel's videos (the "Your videos" section); POST creates a draft.
  let draftBody: unknown;
  await page.route(CHANNEL_VIDEOS, (route) => {
    if (route.request().method() === "POST") {
      draftBody = route.request().postDataJSON();
      return route.fulfill({ json: video({ state: "draft" }) });
    }
    return route.fulfill({ json: { videos: [] } });
  });
  await page.route(UPLOAD, (route) => route.fulfill({ json: { video: video() } }));
  await page.route(VIDEO_CONFIG, (route) => route.fulfill({ json: videoConfig() }));

  await page.getByRole("link", { name: "Studio" }).click();
  await page.getByLabel("Video title").fill("My clip");
  await page.getByLabel("Video description").fill("A short description.");
  await page.getByLabel("Video category").selectOption("7");
  await page.getByLabel("Video language").selectOption("en");
  await page.getByLabel("Video license").selectOption("1");
  await page.getByLabel("Video file").setInputFiles({
    name: "clip.mp4",
    mimeType: "video/mp4",
    buffer: Buffer.from("test"),
  });
  await page.getByRole("button", { name: "Publish" }).click();

  await expect(page.getByText("Published!")).toBeVisible();
  await expect(page.getByRole("link", { name: /View .*My clip/ })).toBeVisible();
  expect(draftBody).toMatchObject({
    title: "My clip",
    description: "A short description.",
    category: "7",
    language: "en",
    license: "1",
  });
});

test("a creator can edit a video's title and privacy", async ({ page }) => {
  await signIn(page);
  await page.route(MY_CHANNELS, (route) =>
    route.fulfill({ json: { channels: [channel("ada_makes", "Ada Makes")] } }),
  );
  await page.route(CHANNEL_VIDEOS, (route) =>
    route.fulfill({ json: { videos: [video({ title: "Old title", privacy: "public" })] } }),
  );
  let patchBody: unknown;
  await page.route(VIDEO, (route) => {
    if (route.request().method() === "PATCH") {
      patchBody = route.request().postDataJSON();
      return route.fulfill({ json: video({ title: "New title", privacy: "unlisted" }) });
    }
    // GET: the edit form fetches the full detail to pre-fill (list lacks taxonomy).
    return route.fulfill({ json: video({ title: "Old title", privacy: "public" }) });
  });
  await page.route(VIDEO_CONFIG, (route) => route.fulfill({ json: videoConfig() }));

  await page.getByRole("link", { name: "Studio" }).click();
  // Scope privacy assertions to the video row — "Public"/"Unlisted" also appear as
  // <option>s in the upload form's privacy <select>.
  const row = page.getByRole("listitem").filter({ hasText: "Old title" });
  await expect(row).toBeVisible();
  await expect(row.getByText("Public")).toBeVisible();

  await row.getByRole("button", { name: "Edit" }).click();
  // The edit form is pre-filled from the video; description + taxonomy are editable.
  await page.getByLabel("Edit title").fill("New title");
  await page.getByLabel("Edit description").fill("Updated description.");
  await page.getByLabel("Edit category").selectOption("1");
  await page.getByLabel("Edit language").selectOption("fr");
  await page.getByLabel("Edit privacy").selectOption("unlisted");
  await page.getByRole("button", { name: "Save" }).click();

  const updatedRow = page.getByRole("listitem").filter({ hasText: "New title" });
  await expect(updatedRow.getByRole("link", { name: "New title" })).toBeVisible();
  await expect(updatedRow.getByText("Unlisted")).toBeVisible();
  expect(patchBody).toMatchObject({
    title: "New title",
    description: "Updated description.",
    category: "1",
    language: "fr",
  });
});

test("a creator can add and remove a caption from a video's edit surface", async ({ page }) => {
  await signIn(page);
  await page.route(MY_CHANNELS, (route) =>
    route.fulfill({ json: { channels: [channel("ada_makes", "Ada Makes")] } }),
  );
  await page.route(CHANNEL_VIDEOS, (route) =>
    route.fulfill({ json: { videos: [video({ title: "Captioned clip" })] } }),
  );
  // The captions list starts empty; POST returns the created track.
  await page.route(CAPTIONS, (route) => {
    if (route.request().method() === "POST") {
      return route.fulfill({
        status: 201,
        json: { language: "en", label: "English", created_at: new Date().toISOString() },
      });
    }
    return route.fulfill({ json: { captions: [] } });
  });
  await page.route(CAPTION_LANG, (route) =>
    route.request().method() === "DELETE" ? route.fulfill({ status: 204, body: "" }) : route.continue(),
  );
  // Entering edit mode fetches the video detail to pre-fill the form. Mock the
  // taxonomy config as empty so the dropdowns carry no options — this
  // caption-focused test stays deterministically isolated from taxonomy labels
  // (e.g. a "English" language option colliding with the caption label).
  await page.route(VIDEO, (route) => route.fulfill({ json: video({ title: "Captioned clip" }) }));
  await page.route(VIDEO_CONFIG, (route) =>
    route.fulfill({ json: { categories: [], licenses: [], languages: [], privacies: [] } }),
  );

  await page.getByRole("link", { name: "Studio" }).click();
  const row = page.getByRole("listitem").filter({ hasText: "Captioned clip" });
  await row.getByRole("button", { name: "Edit" }).click();

  // The captions manager appears (empty).
  await expect(page.getByText("No captions yet.")).toBeVisible();

  // Upload an English caption.
  await page.getByLabel("Caption language").fill("en");
  await page.getByLabel("Caption label").fill("English");
  await page.getByLabel("Caption file").setInputFiles({
    name: "cap.vtt",
    mimeType: "text/vtt",
    buffer: Buffer.from("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHi\n"),
  });
  const uploaded = page.waitForResponse(
    (r) => CAPTIONS.test(r.url()) && r.request().method() === "POST" && r.ok(),
  );
  await page.getByRole("button", { name: "Upload" }).click();
  await uploaded;

  await expect(page.getByText("No captions yet.")).toHaveCount(0);
  await expect(page.getByText("English")).toBeVisible();

  // Remove it.
  const removed = page.waitForResponse(
    (r) => CAPTION_LANG.test(r.url()) && r.request().method() === "DELETE" && r.ok(),
  );
  await page.getByRole("button", { name: "Remove en caption" }).click();
  await removed;
  await expect(page.getByText("No captions yet.")).toBeVisible();
});

test("a creator can delete a video", async ({ page }) => {
  await signIn(page);
  await page.route(MY_CHANNELS, (route) =>
    route.fulfill({ json: { channels: [channel("ada_makes", "Ada Makes")] } }),
  );
  await page.route(CHANNEL_VIDEOS, (route) =>
    route.fulfill({ json: { videos: [video({ title: "Doomed clip" })] } }),
  );
  await page.route(VIDEO, (route) => {
    if (route.request().method() === "DELETE") return route.fulfill({ status: 204 });
    return route.continue();
  });

  await page.getByRole("link", { name: "Studio" }).click();
  await expect(page.getByRole("link", { name: "Doomed clip" })).toBeVisible();

  await page.getByRole("button", { name: "Delete" }).click();
  await page.getByRole("button", { name: "Confirm" }).click();

  await expect(page.getByRole("link", { name: "Doomed clip" })).toHaveCount(0);
  await expect(page.getByText("No videos in this channel yet.")).toBeVisible();
});
