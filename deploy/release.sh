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
#   3. meta tag     — this repository gets the SAME tag, pushed, before any
#                     release is created (see below).
#   4. per repo     — gh release create -> watch the publish-container run to
#                     conclusion -> verify the image actually exists in GHCR.
#
# WHY THIS REPOSITORY IS TAGGED AND YET IS NOT IN ALL_REPOS
#
# vidra-core's release-assets workflow builds the no-git deployment bundle by
# checking THIS repository out at the same tag and running deploy/make-bundle.sh
# from it. The bundle therefore has a provenance — one meta commit, one core
# commit, both recorded in vidra-bundle.manifest — instead of being "whatever
# main happened to be that afternoon". If the tag is missing the workflow fails
# loudly rather than guessing, so the tag has to exist BEFORE the vidra-core
# release is created; that is why it happens first, above the loop.
#
# It stays out of ALL_REPOS because that loop does three things this repo cannot:
# create a GitHub release, watch a publish-container.yml run, and verify an image
# in GHCR. There is no image here. A tag is the whole contract.
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
# This repository. Tagged, never released — see the header.
META_REPO="vidra"
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
    -h|--help) sed -n '2,49p' "$0"; exit 0 ;;
    -*) die "unknown option: $1" ;;
    *)
      if [ -z "$TAG" ]; then TAG="$1"; else REPOS+=("$1"); fi
      shift
      ;;
  esac
done

[ -n "$TAG" ] || die "usage: $0 [--yes] vX.Y.Z [repo ...]  (default repos: ${ALL_REPOS[*]})"
[ ${#REPOS[@]} -gt 0 ] || REPOS=("${ALL_REPOS[@]}")

# THE MACHINE-READABLE RELEASE RECORD (finding #189). deploy/deploy.sh and
# rollback.sh read releases/<tag>.json to refuse a component triple nobody
# released; until now that file was hand-written out of band, so the script that
# cut the tag never wrote the record that names the tag's image digests. This
# script now writes it — but only for a WHOLE platform release (all three repos):
# a record describes core+user+search released together, so a subset re-publish
# of one image after a partial failure does not change the pairing and must not
# rewrite (or half-write) the record. It is written AFTER the images publish,
# because the record names digests that do not exist until then, and it lands via
# a short-lived branch + an auto-opened PR — never a direct push to main, which is
# branch-protected (ci-required + enforce_admins) and would REJECT a fresh commit,
# degrading to the exact by-hand step #189 removes. Every record to date landed by
# PR (v0.6.4 #189, v0.6.5 #196, v0.6.6 #209); this just opens that PR for you. The
# tag stays at the reviewed commit and `meta_commit` stays equal to the tag's
# commit, the convention every existing record and tests/release_mapping_test.py
# assume.
RECORD_REL="releases/${TAG}.json"
RECORD_PATH="${REPO_ROOT}/${RECORD_REL}"
RECORD_HELPER="${REPO_ROOT}/deploy/release-record.py"
FULL_RELEASE=0
if [ ${#REPOS[@]} -eq ${#ALL_REPOS[@]} ]; then
  FULL_RELEASE=1
  for want in "${ALL_REPOS[@]}"; do
    case " ${REPOS[*]} " in *" $want "*) ;; *) FULL_RELEASE=0 ;; esac
  done
fi

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

# --- the meta tag, decided here and applied after the confirmation ------------
# Everything about it that can be refused is refused now, with the rest of the
# pre-flight, because this repository is tagged BEFORE the first release is
# created and a refusal after that point is a half-published release.
#
# META_TAG_ACTION ends up as either `push` (create it) or `skip` (it is already
# there, on the very commit that would be tagged — which is what a re-run for a
# subset of repos looks like, and refusing that would make the subset form of
# this script unusable after any partial failure).
META_TAG_ACTION=push
META_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || true)"
[ -n "$META_SHA" ] || die "$REPO_ROOT is not a git checkout, so this repository cannot be tagged ${TAG} — and vidra-core's release-assets workflow checks it out at that tag to build the deployment bundle."

# The tag is pushed to `origin`, and release-assets checks out ${OWNER}/vidra.
# If those are two different repositories the release looks fine here and the
# bundle step fails on a tag that exists somewhere else entirely.
META_ORIGIN="$(git -C "$REPO_ROOT" remote get-url origin 2>/dev/null || true)"
case "$META_ORIGIN" in
  *"${OWNER}/${META_REPO}"|*"${OWNER}/${META_REPO}.git") ;;
  "") die "$REPO_ROOT has no 'origin' remote, so the ${TAG} tag cannot be pushed anywhere." ;;
  *) die "this checkout's origin is ${META_ORIGIN}, but the release is being cut for ${OWNER}. The tag would be pushed to one repository while vidra-core's release-assets workflow checks a different one out to build the bundle. Set GITHUB_OWNER to the owner this checkout actually pushes to." ;;
esac

# The tag must name a commit the remote already has. `git push` would happily
# send the missing objects along with it, which is how unreviewed local work gets
# published under a release tag; making the check explicit turns that into a
# refusal with a diagnosis instead.
git -C "$REPO_ROOT" fetch --quiet origin main \
  || die "could not fetch origin/main in $REPO_ROOT — the meta tag has to point at a commit that is already on the remote"
if ! git -C "$REPO_ROOT" merge-base --is-ancestor "$META_SHA" origin/main; then
  die "HEAD ($(git -C "$REPO_ROOT" rev-parse --short HEAD)) is not on origin/main, so tagging it ${TAG} would push unreviewed commits under a release tag. Land the work first (or check out the commit you mean), then re-run."
fi

# PEELED FIRST (`^{}`). An annotated tag's ref points at the TAG OBJECT, whose
# sha is not the commit's — comparing that with HEAD reports a perfectly correct
# tag as pointing "somewhere else", and the release stops for no reason. ls-remote
# asks the remote this checkout will actually push to, which is the same question
# the push is about; `gh api` would answer for ${OWNER} instead, and the two are
# only the same repository because of the check above.
remote_tag_commit() {
  git -C "$REPO_ROOT" ls-remote origin "refs/tags/$1^{}" "refs/tags/$1" 2>/dev/null | awk '
    $2 ~ /\^\{\}$/  { peeled = $1 }
    $2 !~ /\^\{\}$/ { plain  = $1 }
    END { print (peeled != "" ? peeled : plain) }
  '
}
META_REMOTE_SHA="$(remote_tag_commit "$TAG")"
if [ -z "$META_REMOTE_SHA" ]; then
  log "tag ${TAG} is free in: ${META_REPO} (this repository, tagged not released)"
elif [ "$META_REMOTE_SHA" = "$META_SHA" ]; then
  META_TAG_ACTION=skip
  log "tag ${TAG} already exists in ${OWNER}/${META_REPO} at this very commit — it will be left alone"
else
  die "tag ${TAG} already exists in ${OWNER}/${META_REPO} but points at ${META_REMOTE_SHA}, not at HEAD (${META_SHA}). The deployment bundle for this release would be built from that other commit. Releases are immutable here: pick the next version, or delete that tag deliberately if it was never released."
fi

# --- the release record: everything that can be refused, refused now ----------
# The record is written after the images publish (see below), but a reason it
# CANNOT be written must surface here, before the outward-facing release, not
# after the images are already public. Only for a whole platform release.
if [ "$FULL_RELEASE" = 1 ]; then
  [ -f "$RECORD_HELPER" ] \
    || die "deploy/release-record.py is missing, so ${RECORD_REL} cannot be assembled. Restore it from this revision and re-run."
  command -v python3 >/dev/null 2>&1 \
    || die "python3 not found — it assembles ${RECORD_REL} (the deploy-script tests use it too). Install it and re-run."
  # buildx resolves the index and per-platform digests the record names. It is
  # the same tool deploy/release-preflight.py requires to freeze a release, so it
  # is part of the release toolchain, not a new dependency — but assert it now.
  docker buildx version >/dev/null 2>&1 \
    || die "docker buildx not found — it resolves the image digests ${RECORD_REL} records (deploy/release-preflight.py needs it too). Install it and re-run."
  # Records are immutable like tags. If one already exists this release was
  # already recorded; refuse rather than clobber a committed record.
  [ ! -e "$RECORD_PATH" ] \
    || die "${RECORD_REL} already exists, so ${TAG} was already recorded. Records are immutable like the tag; pick the next version, or remove that file deliberately if it was written in error and never released."
  # The record lands as a PR whose branch forks HEAD, so this checkout must BE
  # main at origin/main's tip — then the record branch is origin/main plus exactly
  # the record commit, and the PR is a clean data-only diff.
  META_BRANCH="$(git -C "$REPO_ROOT" symbolic-ref --quiet --short HEAD || true)"
  [ "$META_BRANCH" = "main" ] \
    || die "the release record is opened as a PR off main, but this checkout is on '${META_BRANCH:-a detached HEAD}'. Check out main at origin/main and re-run."
  if [ "$META_SHA" != "$(git -C "$REPO_ROOT" rev-parse origin/main)" ]; then
    die "HEAD ($(git -C "$REPO_ROOT" rev-parse --short HEAD)) is not at origin/main's tip, so the record PR would carry unrelated local commits. Update main and re-run."
  fi
fi

# A GitHub release notifies watchers and shows up on the repo's front page. It is
# the one step in this file that reaches people outside the machine, so it asks.
if [ "$ASSUME_YES" = "1" ]; then
  log "--yes given — not prompting."
elif [ -t 0 ]; then
  echo ""
  echo "About to PUBLISH release ${TAG} in: ${REPOS[*]}"
  echo "This is public: it tags the repo, notifies watchers, and pushes"
  echo "ghcr.io/${OWNER}/<repo>:${TAG}. GitHub releases are not meant to be deleted."
  if [ "$META_TAG_ACTION" = "push" ]; then
    echo "It also tags THIS repository ${TAG} at $(git -C "$REPO_ROOT" rev-parse --short HEAD) and pushes"
    echo "that tag first — vidra-core's release-assets workflow builds the deployment"
    echo "bundle from a checkout of it, and fails the release if it is not there."
  fi
  if [ "$FULL_RELEASE" = 1 ]; then
    echo "After the images publish it writes ${RECORD_REL} (the deploy/rollback"
    echo "release record) and opens a PR to add it to main."
  fi
  read -r -p "Type \"${TAG}\" to confirm: " answer
  [ "$answer" = "$TAG" ] || { echo "Aborted."; exit 1; }
else
  die "refusing to publish a release without confirmation and without a terminal. Re-run interactively, or pass --yes if you really mean it."
fi

step "1/2 publish"

# THE META TAG GOES FIRST. vidra-core's release-assets workflow checks this
# repository out at ${TAG} to build vidra-bundle_${TAG}.tar.gz, and it fails the
# job if the tag is not there — so the tag has to exist before the vidra-core
# release triggers that workflow, not after.
if [ "$META_TAG_ACTION" = "push" ]; then
  # A local tag with no remote twin is what the PREVIOUS run left behind if it
  # got here and the push failed. Re-creating it is an error ("tag already
  # exists") and would stop a release for the one reason that needs no fixing, so
  # the existing tag is reused when it names the same commit — and refused when
  # it does not, because then the local repository disagrees with itself about
  # what ${TAG} is.
  local_sha="$(git -C "$REPO_ROOT" rev-parse -q --verify "refs/tags/${TAG}^{commit}" 2>/dev/null || true)"
  if [ -z "$local_sha" ]; then
    log "tagging ${OWNER}/${META_REPO} ${TAG} at ${META_SHA}"
    git -C "$REPO_ROOT" tag -a "$TAG" -m "vidra ${TAG}" "$META_SHA" \
      || die "could not create tag ${TAG} locally in $REPO_ROOT"
  elif [ "$local_sha" = "$META_SHA" ]; then
    log "local tag ${TAG} already exists at this commit (a previous run got this far and could not push) — pushing it"
  else
    die "a LOCAL tag ${TAG} already exists in $REPO_ROOT at ${local_sha}, which is not HEAD (${META_SHA}), and the remote has no ${TAG} at all. Nothing has been released. Delete or move the local tag ('git tag -d ${TAG}') once you know which commit this release is meant to be."
  fi
  # refs/tags/… in full: an unqualified push of a name that also exists as a
  # branch pushes the branch.
  git -C "$REPO_ROOT" push origin "refs/tags/${TAG}" \
    || die "could not push tag ${TAG} to origin. Nothing has been released yet. Check that you can push tags to ${OWNER}/${META_REPO}, then re-run — the local tag is already there, so the next run just pushes it."
  log "pushed ${OWNER}/${META_REPO} ${TAG}"
fi

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

# --- writing releases/<tag>.json (finding #189) -------------------------------
# All of this runs AFTER the images are public, so a failure here does not undo a
# release; it means the record is missing and must be opened as a PR by hand. Say
# that loudly rather than exiting as if the release itself failed.
#
# The block between the markers below is extracted and sourced by
# tests/release_record_landing_test.py to assert the branch+PR landing without a
# real GitHub — keep the markers, and keep the block self-contained (it depends
# only on the vars/log/step/python3 the test supplies and the git/gh/docker it
# stubs).
# >>> release-record functions >>>
record_die() {
  printf '[release] ERROR: %s\n' "$*" >&2
  cat >&2 <<EOF

[release] ${TAG} IS PUBLISHED, but ${RECORD_REL} was NOT written.
  The images are live and verified; only the machine-readable record is missing,
  which leaves deploys of ${TAG} UNVERIFIED (a warning), not broken. Fix the cause,
  then finish it by hand: assemble ${RECORD_REL} and open a PR against main (the
  record cannot be pushed straight to a protected main). For each of vidra-core,
  vidra-user, vidra-search:
      docker buildx imagetools inspect ghcr.io/${OWNER}/<repo>:${TAG} \\
        --format '{{json .Manifest}}' > /tmp/<repo>.mf.json
  then deploy/release-record.py skeleton … | complete (see its --help), then
      git switch -c releases/record-${TAG} && git add ${RECORD_REL} && git commit …
      git push -u origin releases/record-${TAG}
      gh pr create --repo ${OWNER}/${META_REPO} --base main --head releases/record-${TAG} --title "releases: record ${TAG}"
EOF
  exit 1
}

# Echo the 40-hex commit the component's ${TAG} points at, or return 1 (the tag
# was just created by gh release create, so it resolves to a commit). This runs
# inside $(command substitution), so it must RETURN, never exit — an exit would
# only leave the subshell and hand the caller an empty string.
component_commit() {
  local repo="$1" sha
  sha="$(gh api "repos/${OWNER}/${repo}/commits/${TAG}" --jq '.sha' 2>/dev/null || true)"
  case "$sha" in
    *[!0-9a-f]* | '') printf '[release] could not resolve %s commit at %s (got %s)\n' "$repo" "$TAG" "${sha:-empty}" >&2; return 1 ;;
  esac
  [ "${#sha}" -eq 40 ] || { printf '[release] %s commit at %s is not 40 hex (%s)\n' "$repo" "$TAG" "$sha" >&2; return 1; }
  printf '%s\n' "$sha"
}

# Echo the component's schema version: the highest leading number among
# migrations/*.up.sql at ${ref}, read from GitHub — the SAME pipeline deploy.sh
# and make-bundle.sh use on a checkout (`ls migrations/*.up.sql` -> leading
# number, numerically highest). Numeric so 0146 and 146 compare equal, then
# 10#-normalised to the plain integer release-mapping.py requires. RETURNs on
# failure (called in a substitution).
# NOTE: the GitHub contents API lists at most 1000 entries for a directory
# unpaginated; migrations dirs are far below that today (core ~146, search ~18,
# each with up+down files), but past ~500 pairs this would need the Git Trees API.
component_schema() {
  local repo="$1" ref="$2" names max
  names="$(gh api "repos/${OWNER}/${repo}/contents/migrations?ref=${ref}" --jq '.[].name' 2>/dev/null || true)"
  max="$(printf '%s\n' "$names" | grep -E '\.up\.sql$' | awk -F_ '{print $1}' | sort -n | tail -1 || true)"
  case "$max" in
    '' | *[!0-9]*) printf '[release] could not compute %s schema from migrations at %s\n' "$repo" "$ref" >&2; return 1 ;;
  esac
  printf '%s\n' "$((10#$max))"
}

# Resolve one image's index + per-platform digests into $out, exactly as
# release-preflight froze v0.6.5 — `imagetools inspect … {{json .Manifest}}`,
# which deploy/release-record.py then parses. Runs directly (not in a
# substitution), so record_die here stops the script.
resolve_manifest() {
  local repo="$1" out="$2"
  docker buildx imagetools inspect "ghcr.io/${OWNER}/${repo}:${TAG}" --format '{{json .Manifest}}' > "$out" 2>/dev/null \
    || record_die "docker buildx imagetools inspect failed for ghcr.io/${OWNER}/${repo}:${TAG}; the image digests could not be resolved."
}

# Build the skeleton from the now-published facts, fill the digests, and commit
# the finished record to main. meta_commit is the commit the meta tag points at,
# preserving the record convention (see the pre-flight note). Every git step is
# gated on its own exit code — never `add && commit && push`.
write_release_record() {
  step "recording ${RECORD_REL}"
  local meta_commit core_commit user_commit search_commit core_schema search_schema
  local tmp skel record_branch pr_url

  meta_commit="$(git -C "$REPO_ROOT" rev-parse "${TAG}^{commit}" 2>/dev/null || true)"
  case "$meta_commit" in
    *[!0-9a-f]* | '') record_die "could not resolve the meta tag ${TAG} to a commit." ;;
  esac

  core_commit="$(component_commit vidra-core)"     || record_die "could not resolve the vidra-core commit at ${TAG}."
  user_commit="$(component_commit vidra-user)"     || record_die "could not resolve the vidra-user commit at ${TAG}."
  search_commit="$(component_commit vidra-search)" || record_die "could not resolve the vidra-search commit at ${TAG}."
  core_schema="$(component_schema vidra-core "$core_commit")"       || record_die "could not compute the core schema version."
  search_schema="$(component_schema vidra-search "$search_commit")" || record_die "could not compute the search schema version."

  tmp="$(mktemp -d)" || record_die "could not create a temporary directory for the record."
  # shellcheck disable=SC2064  # expand $tmp now so the cleanup targets THIS dir.
  trap "rm -rf '$tmp'" RETURN
  skel="$tmp/skeleton.json"

  python3 "$RECORD_HELPER" skeleton \
    --release "$TAG" --meta-commit "$meta_commit" \
    --core-schema "$core_schema" --search-schema "$search_schema" \
    --evidence "docs/evidence/release-${TAG}-verification/manifest.json" \
    --component "core:${TAG}:${core_commit}:ghcr.io/${OWNER}/vidra-core" \
    --component "user:${TAG}:${user_commit}:ghcr.io/${OWNER}/vidra-user" \
    --component "search:${TAG}:${search_commit}:ghcr.io/${OWNER}/vidra-search" \
    --out "$skel" \
    || record_die "could not assemble the ${RECORD_REL} skeleton."

  resolve_manifest vidra-core   "$tmp/core.mf.json"
  resolve_manifest vidra-user   "$tmp/user.mf.json"
  resolve_manifest vidra-search "$tmp/search.mf.json"

  python3 "$RECORD_HELPER" complete --record "$skel" \
    --manifest "core=$tmp/core.mf.json" \
    --manifest "user=$tmp/user.mf.json" \
    --manifest "search=$tmp/search.mf.json" \
    --out "$RECORD_PATH" \
    || record_die "could not fill the image digests into ${RECORD_REL}."

  # main is branch-protected (ci-required + enforce_admins), so a fresh commit
  # pushed straight to it is REJECTED. Land the record the way every record to
  # date did: a short-lived branch and a PR. It is a data-only change, so
  # ci-required passes trivially and the owner merges it. Each git step is gated
  # on its own exit code — never `add && commit && push`.
  record_branch="releases/record-${TAG}"
  git -C "$REPO_ROOT" checkout -b "$record_branch" \
    || record_die "could not create the record branch ${record_branch} (does it already exist?)."
  git -C "$REPO_ROOT" add -- "$RECORD_REL" \
    || record_die "git add ${RECORD_REL} failed."
  git -C "$REPO_ROOT" commit -q -m "releases: record ${TAG} (written by deploy/release.sh after publish)" -- "$RECORD_REL" \
    || record_die "could not commit ${RECORD_REL}."
  git -C "$REPO_ROOT" push -u origin "$record_branch" \
    || record_die "could not push ${record_branch}. The record commit is local on that branch; push it and open the PR by hand."
  pr_url="$(gh pr create --repo "${OWNER}/${META_REPO}" --base main --head "$record_branch" \
    --title "releases: record ${TAG}" \
    --body "Machine-readable release record for ${TAG}, written by deploy/release.sh after the images were published and verified. Data-only (${RECORD_REL}); ci-required passes trivially. Merge to complete the release." 2>&1)" \
    || record_die "gh pr create failed for ${record_branch}: ${pr_url}. The branch is pushed; open the PR by hand: gh pr create --repo ${OWNER}/${META_REPO} --base main --head ${record_branch} --title \"releases: record ${TAG}\""
  log "opened the record PR: ${pr_url}"
  # Back to main so the operator's checkout is where they started; the record now
  # lives on ${record_branch}. Non-fatal: the record is already pushed and PR'd.
  git -C "$REPO_ROOT" checkout -q main \
    || log "note: could not switch back to main; you are on ${record_branch} (the record PR is open)."
}
# <<< release-record functions <<<

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

# Every image is published and verified. Write the record that names them, so the
# release no longer depends on someone hand-crafting releases/<tag>.json out of
# band (finding #189). Only for a full platform release — see the top-of-file note.
if [ "$FULL_RELEASE" = 1 ]; then
  write_release_record
else
  log "subset release (${REPOS[*]}): ${RECORD_REL} was not written — a release record describes a full core+user+search release. Cut the full release, or complete the record by hand once all three images are green."
fi

log "released ${TAG} in: ${REPOS[*]}"
if [ "$FULL_RELEASE" = 1 ]; then
  log "to ship it, on the host AS THE DEPLOY USER: ./deploy/pin-release.sh ${TAG} && ./deploy/deploy.sh"
else
  # A SUBSET RELEASE HAS NO RECORD YET, and pin-release.sh reads the record to
  # learn which tag each component carries. With none it falls back to pinning
  # all three keys at ${TAG} — correct for a uniform release, and for this one
  # a pin of images that were never built: the deploy would die at
  # `compose pull`. So the hint names the flags rather than the bare form, and
  # stops naming deploy.sh: the tags have to be filled in first.
  log "to ship it, on the host AS THE DEPLOY USER — ${REPOS[*]} moved to ${TAG} and the others did NOT, and ${RECORD_REL} does not exist yet to say so, so name the tags the other components stay at: ./deploy/pin-release.sh ${TAG} --component-tag <role>=<their tag> ... && ./deploy/deploy.sh"
fi
