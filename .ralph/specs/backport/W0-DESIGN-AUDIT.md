# W0 — Design audit of current `vidra-user` (2026-07-07)

## Finding: token migration is DONE; the gap is template/visual parity

A full sweep of `app/` + `components/` found **zero** legacy color utilities
(`bg-gray-*`, `text-zinc-*`, `dark:` branches, raw hex in className). All 21 UI
primitives, all 90 feature components, and all 52 pages use the semantic
`light-dark()` token system (or delegate to primitives that do). Documented
exceptions only: `EmbedPlayer.tsx` and `StoryboardPreview.tsx` media overlays.

**Therefore W0 is NOT a token-migration wave.** "Still on the old design" means
screens are token-compliant but do not match the visual/layout language of the
canonical templates:

- `vidra-user/.ralph/specs/design/desktop-template.jpeg`
- `vidra-user/.ralph/specs/design/app-template.jpeg`

## Template language to enforce (from the JPEGs)

- **Desktop:** left sidebar — Home / Trending / Subscriptions / Library / History /
  Messages / Studio + FOLLOWING section with channel avatars and unread dots;
  centered header search ("Search videos, channels, tags"); `+ Create` pill button;
  notification bell with dot; 3-column video grid.
- **Mobile:** bottom tab bar — Home / Search / Create / Inbox / Library; large
  page title ("Vidra"); compact header with bell + avatar.
- **Shared:** pill filter chips (Recent / Popular / Trending, filled=active);
  "Live now" rail with `● LIVE` badge + "1.2K watching" chip; `IPFS` badge on
  cards; duration chip bottom-right; rounded-2xl thumbnails; title-first metadata
  (channel · views · age in muted second line); generous whitespace; no boxed cards
  (borderless thumbnails on page background).

## W0 execution shape (screen-by-screen visual parity pass)

For each feature area, one vertical task: screenshot current screen (Playwright,
light + dark, mobile + desktop) → diff against template language above → restyle →
re-screenshot → attach before/after to the commit/PR body. Suggested order
(user-facing impact first):

1. Home / feed (chips, live rail, card treatment, grid)
2. Watch page (player chrome, metadata block, related rail)
3. Channel page + subscriptions/following affordances
4. Search + trending + library + history
5. Studio (creator surfaces)
6. Settings (all tabs)
7. Messages / notifications
8. Admin + moderation (utilitarian screens — HIG tables, toolbars, empty states)
9. Auth screens (login/signup/reset)

Acceptance per task: matches template language; tokens only (grep guard stays
green); e2e suite green; before/after screenshots recorded.
