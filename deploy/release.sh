#!/usr/bin/env bash
#
# Cut a GitHub release in each component repo and wait for GHCR to have the
# image the deploy scripts will later pull.
#
#   ./deploy/release.sh v0.2.0                          # all three repos
#   ./deploy/release.sh v0.2.0 vidra-core vidra-search  # a subset
#   ./deploy/release.sh --yes v0.2.0                    # no confirmation prompt
#
# Each repo's .github/workflows/publish-container.yml runs on `release:
# published` and pushes ghcr.io/<owner>/<repo>:<tag>, so "cut a release" and
# "publish an image" are the same act — this script does it in one place, in a
# fixed order, and refuses early rather than half-way:
#
#   1. pre-flight   — tag shape, gh auth, tag not already taken in ANY target
#                     repo, and (for vidra-user) the repository variable its
#                     workflow gates on. All of it BEFORE the first release is
#                     created, because a GitHub release is outward-facing: it
#                     mails watchers and it cannot be un-announced.
#   2. confirm      — one prompt, skippable with --yes for a scripted release.
#   3. per repo     — gh release create -> watch the publish-container run to
#                     conclusion -> verify the image actually exists in GHCR.
#
# It keeps going after a repo fails so one broken build does not hide the state
# of the others, and exits non-zero with a per-image summary at the end.
#
# It does NOT deploy anything. Publishing an image and running it are separate
# decisions: bump VIDRA_*_TAG in env/production.env and run ./deploy/deploy.sh
# when you want this release live.
#
# Re-publishing a tag that already exists is deliberately NOT this script's job
# (it would have to delete a release). Use the workflow's dispatch trigger:
#     gh workflow run publish-container.yml -R <owner>/<repo> -f tag=v0.2.0

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

OWNER="${GITHUB_OWNER:-yegamble}"
ALL_REPOS=(vidra-core vidra-user vidra-search)
# How long to wait for GitHub to create the workflow run after the release is
# published. It is normally 2-5s; the wait exists so a slow webhook does not get
# reported as "no run was triggered".
RUN_APPEAR_TIMEOUT="${RUN_APPEAR_TIMEOUT:-120}"

log()  { printf '[release] %s\n' "$*"; }
die()  { printf '[release] ERROR: %s\n' "$*" >&2; exit 1; }
step() { printf '\n[release] ===== %s =====\n' "$*"; }

ASSUME_YES=0
TAG=""
REPOS=()
while [ $# -gt 0 ]; do
  case "$1" in
    -y|--yes)  ASSUME_YES=1; shift ;;
    -h|--help) sed -n '2,33p' "$0"; exit 0 ;;
    -*) die "unknown option: $1" ;;
    *)
      if [ -z "$TAG" ]; then TAG="$1"; else REPOS+=("$1"); fi
      shift
      ;;
  esac
done

[ -n "$TAG" ] || die "usage: $0 [--yes] vX.Y.Z [repo ...]  (default repos: ${ALL_REPOS[*]})"
[ ${#REPOS[@]} -gt 0 ] || REPOS=("${ALL_REPOS[@]}")

step "0/2 pre-flight"

# The v-prefix is the documented convention, not decoration: env/production.env
# pins VIDRA_*_TAG=v0.1.1, docker-compose.prod.yml interpolates those straight
# into the image reference, and deploy/rollback.sh copies whatever it is given.
# A "0.2.0" release would publish ghcr.io/<owner>/<repo>:0.2.0 and quietly break
# the one convention every other file here assumes.
if ! printf '%s' "$TAG" | grep -qE '^v[0-9]+\.[0-9]+\.[0-9]+$'; then
  die "tag must match ^v[0-9]+\\.[0-9]+\\.[0-9]+\$ — got '${TAG}'. The leading 'v' is the convention every other file assumes; pre-release/build suffixes are not supported by the deploy tooling."
fi

for repo in "${REPOS[@]}"; do
  case " ${ALL_REPOS[*]} " in
    *" $repo "*) ;;
    *) die "unknown repo '$repo' — pick from: ${ALL_REPOS[*]}" ;;
  esac
done

command -v gh >/dev/null 2>&1 \
  || die "gh (GitHub CLI) not found — install it (https://cli.github.com) and run 'gh auth login'"
gh auth status >/dev/null 2>&1 \
  || die "gh is not authenticated — run 'gh auth login' (needs 'repo' and 'workflow' scopes)"
log "gh $(gh version | head -n1 | awk '{print $3}') authenticated as $(gh api user --jq .login)"

# A release is created from a tag, so an existing tag is an existing release for
# our purposes — and `gh release create` on one fails half-way through the fleet,
# leaving some repos released and some not. Check every target first.
for repo in "${REPOS[@]}"; do
  if gh api "repos/${OWNER}/${repo}/git/ref/tags/${TAG}" >/dev/null 2>&1; then
    die "tag ${TAG} already exists in ${OWNER}/${repo}. Releases are immutable here — pick the next version, or re-publish that tag's image with:
    gh workflow run publish-container.yml -R ${OWNER}/${repo} -f tag=${TAG}"
  fi
done
log "tag ${TAG} is free in: ${REPOS[*]}"

# A GitHub release notifies watchers and shows up on the repo's front page. It is
# the one step in this file that reaches people outside the machine, so it asks.
if [ "$ASSUME_YES" = "1" ]; then
  log "--yes given — not prompting."
elif [ -t 0 ]; then
  echo ""
  echo "About to PUBLISH release ${TAG} in: ${REPOS[*]}"
  echo "This is public: it tags the repo, notifies watchers, and pushes"
  echo "ghcr.io/${OWNER}/<repo>:${TAG}. GitHub releases are not meant to be deleted."
  read -r -p "Type \"${TAG}\" to confirm: " answer
  [ "$answer" = "$TAG" ] || { echo "Aborted."; exit 1; }
else
  die "refusing to publish a release without confirmation and without a terminal. Re-run interactively, or pass --yes if you really mean it."
fi

step "1/2 publish"

# Verify the image the deploy scripts will pull is really in the registry — a
# green workflow is not proof (the push step can be skipped, a tag can be
# overwritten). `docker manifest inspect` is the check that matches what
# `docker compose pull` will do on the droplet; it works anonymously for public
# packages, so the gh fallback is only reached when the package is private or
# docker is unavailable, and it needs a token with read:packages.
verify_image() {
  local repo="$1"
  local ref="ghcr.io/${OWNER}/${repo}:${TAG}" derr="" tags=""
  if command -v docker >/dev/null 2>&1; then
    # 2>&1 >/dev/null keeps stderr (the reason) and drops the manifest itself.
    if derr="$(docker manifest inspect "$ref" 2>&1 >/dev/null)"; then
      log "image verified via 'docker manifest inspect': ${ref}"
      return 0
    fi
  else
    derr="docker not installed"
  fi
  if ! tags="$(gh api --paginate "users/${OWNER}/packages/container/${repo}/versions" \
      --jq '.[].metadata.container.tags[]' 2>&1)"; then
    printf '[release] ERROR: %s\n' "could not verify ${ref}. docker said: ${derr}. gh fallback said: ${tags} (a token with the read:packages scope is needed for private packages)" >&2
    return 1
  fi
  if printf '%s\n' "$tags" | grep -qxF "$TAG"; then
    log "image verified via the GitHub packages API: ${ref} (docker check unavailable: ${derr})"
    return 0
  fi
  printf '[release] ERROR: %s\n' "the GitHub packages API lists no '${TAG}' tag for ${repo}, so ${ref} does not exist (docker check said: ${derr})" >&2
  return 1
}

# The run is created by a webhook a beat after the release, and for a release
# event its headBranch is the tag — which is what makes it identifiable without
# guessing at timestamps.
watch_publish_run() {
  local repo="$1" deadline run_id url
  deadline=$(( $(date +%s) + RUN_APPEAR_TIMEOUT ))
  while :; do
    run_id="$(gh run list -R "${OWNER}/${repo}" --workflow=publish-container.yml \
      --limit 20 --json databaseId,event,headBranch \
      --jq "[.[] | select(.event == \"release\" and .headBranch == \"${TAG}\")] | first | .databaseId" 2>/dev/null || true)"
    case "$run_id" in
      ''|null) ;;
      *) break ;;
    esac
    if [ "$(date +%s)" -ge "$deadline" ]; then
      printf '[release] ERROR: %s\n' "no publish-container run appeared for ${repo} ${TAG} within ${RUN_APPEAR_TIMEOUT}s. Check https://github.com/${OWNER}/${repo}/actions" >&2
      return 1
    fi
    sleep 3
  done
  url="$(gh run view "$run_id" -R "${OWNER}/${repo}" --json url --jq .url)"
  log "watching ${url}"
  gh run watch "$run_id" -R "${OWNER}/${repo}" --exit-status || {
    printf '[release] ERROR: %s\n' "publish-container failed for ${repo} ${TAG}: ${url}" >&2
    return 1
  }
  log "publish-container succeeded for ${repo}"
}

rc=0
RESULTS=()
for repo in "${REPOS[@]}"; do
  step "publishing ${OWNER}/${repo} ${TAG}"
  if ! gh release create "$TAG" -R "${OWNER}/${repo}" --generate-notes --latest; then
    printf '[release] ERROR: %s\n' "gh release create failed for ${repo} — nothing was published for it" >&2
    RESULTS+=("${repo}: release NOT created")
    rc=1
    continue
  fi
  if ! watch_publish_run "$repo"; then
    RESULTS+=("${repo}: release created, image build FAILED — re-run with: gh workflow run publish-container.yml -R ${OWNER}/${repo} -f tag=${TAG}")
    rc=1
    continue
  fi
  if ! verify_image "$repo"; then
    RESULTS+=("${repo}: build green but ghcr.io/${OWNER}/${repo}:${TAG} NOT verified")
    rc=1
    continue
  fi
  RESULTS+=("${repo}: ghcr.io/${OWNER}/${repo}:${TAG} OK")
done

step "2/2 summary"
for line in "${RESULTS[@]}"; do
  log "$line"
done

if [ "$rc" -ne 0 ]; then
  cat >&2 <<EOF

[release] RELEASE ${TAG} IS INCOMPLETE — do not deploy it.
  Fix the failing build and re-publish that repo's image without a new release:
      gh workflow run publish-container.yml -R ${OWNER}/<repo> -f tag=${TAG}
EOF
  exit 1
fi

log "released ${TAG} in: ${REPOS[*]}"
log "to ship it: set VIDRA_CORE_TAG/VIDRA_USER_TAG/VIDRA_SEARCH_TAG=${TAG} in env/production.env, then ./deploy/deploy.sh"
