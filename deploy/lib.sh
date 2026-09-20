#!/usr/bin/env bash
# shellcheck shell=bash
#
# deploy/lib.sh — the parts of the production compose invocation that every
# script touching the running stack MUST agree on. SOURCED, never executed:
# `. "$REPO_ROOT/deploy/lib.sh"`.
#
# WHY THIS FILE EXISTS: deploy.sh, rollback.sh, restore.sh, backup.sh and
# deploy/compose.sh all address the SAME docker-compose project. If two of them
# assemble a different `-f` chain or a different `--profile` set, `ps -q
# postgres` and `up -d` resolve against different renderings of that project —
# `backup.sh` dumps a database `deploy.sh` is not migrating, or `prod-config`
# validates a stack nobody runs. That is not a theoretical drift: this block
# lived as five copies, kept in step by a comment asking future editors to paste
# carefully, and the fifth (the Makefile's PROD_COMPOSE) had already fallen
# behind — it hardcoded `--profile core --profile frontend`, ignored both
# external-datastore overlays, and reported "renders cleanly" for an
# external-Postgres env file while rendering the BUNDLED postgres.
#
# CONTRACT FOR THE CALLER (all five already satisfy it, source this after them):
#   * ENV_FILE  — set, and the file exists. Read at CALL time, not source time.
#   * log()     — defined. The messages below carry the caller's own [tag]
#                 prefix on purpose, so a line about external datastores reads
#                 as `[backup]` or `[deploy]` rather than as coming from here.
#
# PROVIDES
#   env_get KEY [DEFAULT]  value from the process env, else $ENV_FILE, else DEFAULT
#   is_true VALUE          exit 0 for the spellings of "yes" an operator types
#   edge_profile           prints `edge` unless VIDRA_TLS_MODE=external
#   vidra_compose_chain    sets COMPOSE=(...), EXTERNAL_POSTGRES, EXTERNAL_REDIS
#   is_bundle_tree ROOT    exit 0 when ROOT was unpacked, not cloned
#   bundle_manifest_get ROOT KEY [DEFAULT]   one value from vidra-bundle.manifest
#   env_snapshot FILE ROOT keeps 10 timestamped generations of an env file
#   fetch_release_record TAG DEST   best-effort https download of a release
#                          record this tree cannot carry yet; never fatal
#   release_mapping_check ROOT MODE CORE USER SEARCH
#                          exit 0 when releases/ allows this tag triple

# Reads KEY from the env file WITHOUT sourcing it — that file is operator-edited
# and holds secrets; `source`ing it would execute whatever is in there. A real
# exported environment variable of the same name wins, so
# `POSTGRES_DB=other ./deploy/backup.sh` works for one-off runs.
#
# shellcheck disable=SC2154  # ENV_FILE is the caller's, per the contract above.
env_get() {
  local key="$1" def="${2-}" val
  val="$(printenv "$key" 2>/dev/null || true)"
  if [ -z "$val" ]; then
    val="$(sed -n "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//p" "$ENV_FILE" | tail -n1 | tr -d '\r')"
    case "$val" in
      \"*\") val="${val%\"}"; val="${val#\"}" ;;
      \'*\') val="${val%\'}"; val="${val#\'}" ;;
    esac
  fi
  printf '%s' "${val:-$def}"
}

# `is_true` rather than `= true` because operators type true/yes/1
# interchangeably and a typo silently starts a second, empty database next to
# the managed one.
#
# THIS WORD LIST IS THE CONTRACT between the shell here and vidra-core's setup
# engine. The engine only ever WRITES literal `true`/`false`; this list is the
# wider set it must be safe to READ. Do not narrow it — an env file hand-edited
# to `yes` predates the engine and still has to work.
is_true() {
  case "$1" in
    true|TRUE|True|yes|YES|Yes|1|on|ON|On) return 0 ;;
    *) return 1 ;;
  esac
}

# edge_profile — prints `edge` when this deployment runs Vidra's own Caddy, and
# nothing when it does not. Called unquoted inside the profile loop below, so
# "nothing" contributes no word at all.
#
# WHY THE ENGINE DECIDES AND NOT THE OPERATOR: docker-compose.prod.yml's caddy
# service is on the `edge` profile, and if that profile had to be typed into
# VIDRA_COMPOSE_PROFILES then every env file written before this change — every
# one in existence — would silently stop starting the TLS terminator on its next
# deploy. The whole site, gone, because a compose file grew a profile. So the
# rule is inverted: caddy is ON unless the env file says somebody else is
# terminating TLS.
#
# `external` is the ONLY mode that turns it off. plain-http still runs Caddy (as
# a plain-HTTP site — one managed front door, whatever the scheme), and an unset
# or unrecognised value keeps it too: an operator who typos the mode gets a
# refusal from deploy.sh's mode switch, not a silently edge-less stack.
edge_profile() {
  case "$(env_get VIDRA_TLS_MODE acme)" in
    external) ;;
    *) printf 'edge' ;;
  esac
}

# vidra_compose_chain — build the compose invocation from the env file rather
# than hardcoding it, so `vidra setup` can change the SHAPE of the stack
# (external datastores, extra profiles) without editing any of these scripts.
#
# Sets three globals, deliberately: the callers use `"${COMPOSE[@]}"` dozens of
# times and branch on the two flags (backup.sh and restore.sh refuse outright
# when Postgres is managed elsewhere).
#
# An env file that predates these keys — or sets them empty — produces exactly
# the command line these scripts used before there were any, plus the `edge`
# profile that now carries the caddy service (see edge_profile above; the
# service used to have no profile, so this is the same set of containers):
#   docker compose -f docker-compose.yml -f docker-compose.prod.yml \
#     --env-file "$ENV_FILE" --profile core --profile frontend --profile edge
vidra_compose_chain() {
  local profile seen_profiles=""

  COMPOSE=(docker compose
    -f docker-compose.yml
    -f docker-compose.prod.yml)

  if is_true "$(env_get IPFS_MANAGED_NODE false)"; then
    COMPOSE+=(-f docker-compose.ipfs-managed.yml)
  fi

  # External/managed datastores. Each overlay parks the bundled service on a
  # profile nothing enables and deletes every depends_on edge that named it —
  # leaving one in place makes the whole project INVALID, not merely wasteful
  # ("service search-migrate depends on undefined service postgres"). See the
  # header of docker-compose.external-postgres.yml for the merge-tag reasoning.
  #
  # Both overlays MUST come after docker-compose.prod.yml (they build on its
  # `!reset` tags and `${...:?}` assertions), and postgres before redis so every
  # host renders the same chain.
  EXTERNAL_POSTGRES=0
  EXTERNAL_REDIS=0
  if is_true "$(env_get VIDRA_EXTERNAL_POSTGRES false)"; then
    EXTERNAL_POSTGRES=1
    COMPOSE+=(-f docker-compose.external-postgres.yml)
  fi
  if is_true "$(env_get VIDRA_EXTERNAL_REDIS false)"; then
    EXTERNAL_REDIS=1
    COMPOSE+=(-f docker-compose.external-redis.yml)
  fi

  COMPOSE+=(--env-file "$ENV_FILE")

  # Profiles: VIDRA_COMPOSE_PROFILES (default `core frontend` — exactly what
  # these scripts hardcoded before) plus EXTRA_COMPOSE_PROFILES, which stays a
  # separate key because `vidra setup` rewrites the first and the operator owns
  # the second. Both are space-separated lists, so the command substitutions are
  # deliberately unquoted. Duplicates are collapsed in first-seen order: passing
  # --profile core twice changes nothing, but it makes two `ps` outputs annoying
  # to compare.
  # shellcheck disable=SC2046  # word splitting is the point: these are lists.
  for profile in $(env_get VIDRA_COMPOSE_PROFILES "core frontend") $(env_get EXTRA_COMPOSE_PROFILES "") $(edge_profile); do
    case " $seen_profiles " in
      *" $profile "*) continue ;;
    esac
    seen_profiles="$seen_profiles $profile"
    COMPOSE+=(--profile "$profile")
  done

  if [ "$EXTERNAL_POSTGRES" -eq 1 ] || [ "$EXTERNAL_REDIS" -eq 1 ]; then
    log "external datastores: postgres=${EXTERNAL_POSTGRES} redis=${EXTERNAL_REDIS} (the bundled service is disabled by its overlay)"
  fi
}

# is_bundle_tree ROOT — exit 0 when ROOT was UNPACKED from a release bundle
# rather than cloned, and 1 when it is an ordinary git checkout.
#
# TWO CONDITIONS, AND BOTH MATTER. `vidra-bundle.manifest` is written only by
# deploy/make-bundle.sh and is gitignored, so its presence says "unpacked". But
# an operator may perfectly well `git clone` this repo INTO a directory that
# still has an old manifest lying around, or unpack a bundle on top of a
# checkout — and in that tree the component checkouts really are there, with
# their tags and their migrations, so the git path is both available and better.
# Requiring vidra-core/.git to be ABSENT makes the answer describe the tree that
# actually exists instead of an artefact of how it was made.
#
# Neither marker — no manifest and no vidra-core/.git, i.e. somebody copied a
# directory tree by hand — is deliberately NOT a bundle: the callers then reach
# their original "exists but is not a git checkout" refusal, which is still the
# right answer for a tree nobody can identify.
is_bundle_tree() {
  [ -f "$1/vidra-bundle.manifest" ] && [ ! -d "$1/vidra-core/.git" ]
}

# bundle_manifest_get ROOT KEY [DEFAULT] — one value out of the manifest.
#
# Read the same way env_get reads the env file, and for a weaker version of the
# same reason: the file is `key=value` lines with comments, it is not shell, and
# sourcing a file that arrived inside a downloaded tarball to extract four
# strings would be an extraordinary way to execute somebody else's code. Unlike
# env_get there is no process-env precedence — these values describe the artefact
# on disk, and an environment variable cannot change what a tarball contains.
bundle_manifest_get() {
  local root="$1" key="$2" def="${3-}" val
  val="$(sed -n "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//p" "$root/vidra-bundle.manifest" 2>/dev/null | tail -n1 | tr -d '\r')"
  printf '%s' "${val:-$def}"
}

# env_snapshot <env-file> <repo-root> — copy the env file into
# <repo-root>/backups/env-history/<basename>.<UTC %Y%m%dT%H%M%SZ> and keep the
# ten newest snapshots OF THAT BASENAME.
#
# WHY A DIRECTORY AND NOT ANOTHER .bak: `cp "$ENV_FILE" "$ENV_FILE.bak"` records
# exactly ONE generation, and it is overwritten by the next run. Two rollbacks in
# an incident — v0.3.0 is bad, roll to v0.2.1, that is bad too, roll to v0.2.0 —
# and the .bak now holds v0.2.1, the state nobody wants to return to. The tags
# you were serving before the incident started are gone, and they are exactly
# what the incident notes need. Ten generations is cheap (an env file is a couple
# of kilobytes) and covers any plausible run of rollbacks.
#
# THE PATH SHAPE IS A CROSS-LANGUAGE CONTRACT. `vidra update` writes the same
# history from Go; both must agree on the directory, the separator and the stamp
# format or the two halves prune each other's snapshots (or, worse, neither
# prunes and the directory grows without bound). Change it in one place only by
# changing it in both.
#
# The stamp is UTC and fixed-width for the same reason backup.sh's is: these
# names sort lexicographically exactly as they sort chronologically, so the
# retention pass below needs no stat(1), no `date -d` and no mktime().
#
# 0700 on the directory and 0600 on each file because these ARE the secrets —
# JWT_SECRET, POSTGRES_PASSWORD, MFA_KEY_KEK. `cat >` under `umask 077`, not
# `cp` then `chmod`: cp creates the destination with the SOURCE's mode (so a
# hand-created 0644 env file would be copied 0644), and a later chmod leaves a
# window, however short, in which the whole host can read the key-encryption key.
#
# shellcheck disable=SC2154  # log() is the caller's, per the contract above.
env_snapshot() {
  local src="$1" root="$2" base dir stamp dest keep stale
  base="$(basename "$src")"
  dir="$root/backups/env-history"
  keep="${VIDRA_ENV_HISTORY_KEEP:-10}"

  mkdir -p "$dir"
  chmod 700 "$dir"
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  dest="$dir/${base}.${stamp}"
  ( umask 077; cat "$src" > "$dest" )
  log "env snapshot: backups/env-history/${base}.${stamp}"

  # Only this basename's own snapshots, and only names whose suffix really is a
  # stamp: env/staging.env and env/production.env share the directory, and
  # `production.env.*` would otherwise also sweep a hypothetical
  # `production.env.old.<stamp>`. The character classes are spelled out instead
  # of using {8}/{6} because mawk — Ubuntu's default awk, which is what runs this
  # on a droplet — has not always supported interval expressions.
  stale="$(
    { ls -1 -- "$dir" 2>/dev/null || true; } | awk -v b="$base" '
      {
        n = length(b)
        if (substr($0, 1, n + 1) != b ".") next
        s = substr($0, n + 2)
        if (s ~ /^[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z$/) print
      }
    ' | sort -r | tail -n +"$((keep + 1))"
  )"
  if [ -n "$stale" ]; then
    printf '%s\n' "$stale" | while IFS= read -r f; do
      log "pruning env snapshot $f"
      rm -f -- "$dir/$f"
    done
  fi
}

# Set KEY=VAL in $ENV_FILE, in place, via a temp file + cat rather than `sed -i`,
# whose syntax differs between GNU and BSD sed. Appends the key when it is not
# already present, so this also works on an env file that inherited its tags
# from the shell. Lived in rollback.sh until pin-release.sh needed the same
# rewrite; one copy, so the two can never disagree about what a pin looks like.
# Uses the caller's log() and ENV_FILE, per the contract above.
# shellcheck disable=SC2154
env_set_key() {
  local key="$1" val="$2" tmp
  [ -n "$val" ] || return 0
  tmp="$(mktemp)"
  if grep -qE "^[[:space:]]*${key}[[:space:]]*=" "$ENV_FILE"; then
    awk -v k="$key" -v v="$val" '
      $0 ~ "^[[:space:]]*" k "[[:space:]]*=" { print k "=" v; next }
      { print }
    ' "$ENV_FILE" > "$tmp"
  else
    cat "$ENV_FILE" > "$tmp"
    printf '%s=%s\n' "$key" "$val" >> "$tmp"
  fi
  cat "$tmp" > "$ENV_FILE"
  rm -f "$tmp"
  log "set ${key}=${val}"
}

# fetch_release_record TAG DEST — download releases/TAG.json to DEST. Exit 0
# with the record there, 1 otherwise, having LOGGED why and the exact curl to
# run by hand. Uses the caller's log(), per the contract above.
#
# WHY A PREFLIGHT REACHES THE NETWORK AT ALL. deploy/release.sh pushes this
# repository's tag BEFORE it publishes the component releases, because
# vidra-core's release-assets workflow checks the meta repo out at that tag to
# build vidra-bundle_<TAG>.tar.gz and fails the job if the tag is not there. No
# image — and so no digest — exists at that moment, so releases/<TAG>.json is
# written after the publish and lands on main in a PR. A vN tree and the vN
# bundle therefore carry records only up to v(N-1), and deploying the NEWEST
# release compared three tag strings and nothing else: not that these images
# were released together, and not a digest pin on any of them. Downloading the
# record is the only way to close that without rewriting a published,
# checksummed release asset out from under whoever already downloaded it.
#
# curl and not git, deliberately: the beta host runs an UNPACKED bundle tree
# with no git anywhere, and it is the host this has to work on.
#
# WHY NO FAILURE HERE MAY BE FATAL. A record that could not be downloaded
# predicts nothing about the images being deployed, and a finding may only stop
# what it predicts. 404 (the record PR has not merged yet), a timeout, an
# airgapped host, a captive portal, no curl at all: every one of them leaves the
# run with exactly the verdict it already had, plus a warning naming the URL.
# The one thing that stops a deploy is a record that LOADS and CONTRADICTS the
# pins, and that verdict belongs to deploy/release-mapping.py, not here.
# The record source the bundle's own TLS trust anchor already covers: the same
# GitHub repository that served vidra-bundle_<TAG>.tar.gz. Anything else is the
# operator's deliberate choice and is logged as such (see releases/README.md,
# "Trust model").
VIDRA_RECORD_DEFAULT_BASE_URL='https://raw.githubusercontent.com/yegamble/vidra/main/releases'

fetch_release_record() {
  local tag="$1" dest="$2" base url safe_url tmp why switch sub=0 semver_re bytes
  local max=262144   # 256 KiB. A record is ~2 KiB; anything near this is a page, not a record.
  RECORD_FETCHED_FROM=''

  # THE AIRGAPPED SWITCH, read through env_get so it works from the env file
  # and the process environment alike, exactly like VIDRA_SKIP_DNS_PREFLIGHT.
  # Checked FIRST, so a host that turned it off is never seen reaching out and
  # never pays the timeout.
  #
  # NORMALISED HERE, not in env_get. env_get hands back the raw remainder of
  # the line, so `VIDRA_RECORD_FETCH=off  # airgapped` arrived as the whole
  # string "off  # airgapped", matched none of the words and FETCHED ANYWAY —
  # silently doing the one thing the operator wrote that line to prevent. A
  # trailing space did it too. Compose reads an unquoted value the same way
  # this now does (cut at ` #`, trim); the word list mirrors is_true's, because
  # env files are hand-edited and "no" gets typed several ways. Deliberately
  # local: env_get is read by a dozen other keys whose values legitimately
  # contain `#`, and widening it in this change would be a blind edit.
  switch="$(env_get VIDRA_RECORD_FETCH '')"
  switch="${switch%%#*}"
  switch="${switch#"${switch%%[![:space:]]*}"}"
  switch="${switch%"${switch##*[![:space:]]}"}"
  switch="$(printf '%s' "$switch" | tr '[:upper:]' '[:lower:]')"
  case "$switch" in
    off|false|0|no)
      log "VIDRA_RECORD_FETCH is off — not fetching ${tag}'s release record. This run verifies only what the tree itself can prove."
      return 1 ;;
  esac

  # STRICT SEMVER BEFORE ANYTHING IS INTERPOLATED. The tag comes from a
  # VIDRA_*_TAG in an operator-edited env file and goes into BOTH a URL and a
  # filename, so `v1.2.3/../../evil`, `v1.2.3?ref=x` and `v1.2.3 v1.2.4` must be
  # stopped before either. Releases are only ever cut as vMAJOR.MINOR.PATCH
  # (deploy/release.sh), so nothing legitimate is excluded: a prerelease a
  # rehearsal lab deploys has no record upstream to fetch in the first place.
  #
  # `[[ =~ ]]` and not `grep -Eq '^...$'`: grep matches per LINE, so a value
  # containing a newline passes a check that looks airtight — "v1.2.3\nevil"
  # matched, and the second line went on to be interpolated. Bash's =~ anchors
  # against the whole string.
  semver_re='^v[0-9]+\.[0-9]+\.[0-9]+$'
  if [[ ! $tag =~ $semver_re ]]; then
    log "not fetching a release record: this tag is not a vMAJOR.MINOR.PATCH release tag, and only those have records."
    return 1
  fi

  # The fork/mirror knob, alongside VIDRA_IMAGE_REGISTRY/VIDRA_IMAGE_OWNER: a
  # fork publishes its own records, and an egress-filtered network mirrors them.
  base="$(env_get VIDRA_RECORD_BASE_URL "$VIDRA_RECORD_DEFAULT_BASE_URL")"
  base="${base%/}"
  # HTTPS ONLY, here as well as in curl's own --proto below. This record decides
  # what the deploy will verify, so a channel anyone on the path can rewrite is
  # worse than no record at all. Named here rather than left to a curl error, so
  # the message says which key to fix.
  case "$base" in
    https://*) ;;
    *)
      log "not fetching a release record: VIDRA_RECORD_BASE_URL is not an https:// URL, and this record decides what the deploy verifies."
      return 1 ;;
  esac
  url="$base/$tag.json"
  # Credentials in the URL are masked in EVERY line this function logs, the
  # hand-run curl included: a deploy log is read, pasted into tickets and
  # shipped to a log collector, and a token that reaches it is a token to
  # rotate. curl still receives the real URL.
  safe_url="$(printf '%s' "$url" | sed -e 's#://[^/@]*@#://***@#')"

  if [ "$base" != "${VIDRA_RECORD_DEFAULT_BASE_URL%/}" ]; then
    # Not a refusal — a mirror is exactly what VIDRA_RECORD_BASE_URL is for.
    # But the verdict below will rest on bytes from a source the operator
    # chose, not on the one that shipped the bundle, and that has to be in the
    # log beside the verdict rather than inferred from a URL.
    log "WARNING: VIDRA_RECORD_BASE_URL points at a NON-CANONICAL record source ($safe_url). Whatever this run verifies about the release mapping rests on that source, not on the repository this release was published from."
  fi

  if ! command -v curl >/dev/null 2>&1; then
    log "not fetching a release record: curl is not installed on this host. ${tag}'s pairing and digests stay unverified; install curl, or fetch $safe_url by hand onto this tree as releases/${tag}.json."
    return 1
  fi

  # Into a TEMP FILE, never straight to DEST: a truncated, oversized or HTML
  # body must not end up at the path the checker is then pointed at.
  tmp="$(mktemp "${TMPDIR:-/tmp}/vidra-record.XXXXXX" 2>/dev/null)" || tmp=''
  if [ -z "$tmp" ]; then
    log "not fetching a release record: could not create a temporary file."
    return 1
  fi

  # THE DOWNLOAD RUNS IN ITS OWN SUBSHELL so it can own a cleanup trap.
  # lib.sh is SOURCED by deploy.sh and rollback.sh, which install their own
  # EXIT traps; a `trap ... EXIT` at function scope would silently REPLACE
  # one of those. A command substitution is already a subshell, and a trap set
  # inside it is neither seen nor inherited by the caller — so Ctrl-C during
  # the curl (a preflight is exactly when someone changes their mind) removes
  # the partial download instead of leaking it into TMPDIR.
  #
  # curl flags, and why each is load-bearing:
  #   -q FIRST          ignore ~/.curlrc. A deploy host's curl config can add
  #                     --insecure, a --proxy, even another --output, and it is
  #                     not this preflight's to trust. It must precede every
  #                     other argument or the config is applied before them.
  #   --proto/--proto-redir '=https'  TLS on the first hop AND across redirects
  #   --max-redirs      a redirect chain is not a record
  #   --connect-timeout bounds a host that accepts nothing
  #   --max-time        bounds a black-holed host; this runs before anything
  #                     has changed and must never turn a deploy into a hang
  #   --max-filesize    refuses an oversized body at the wire; the byte count
  #                     below catches a chunked response that declares none
  # TWO THINGS MUST NOT APPEAR BETWEEN THE $( AND ITS ), and both cost an hour
  # to find because the gates do not catch either:
  #   * a `case` pattern written with a backslash escape. Its `)` closes the
  #     substitution, and bash then reads the remaining branches as shell
  #     source. The prefix test below is a plain parameter expansion instead.
  #   * a COMMENT CONTAINING AN APOSTROPHE. The substitution scanner does not
  #     treat comments as comments when tracking quotes, so one apostrophe in
  #     a remark opens a string that never closes. (A bare `)` in a comment is
  #     harmless; an apostrophe is not.)
  # `bash -n` passes BOTH of these on the whole file, because a later
  # apostrophe elsewhere re-balances the count, and shellcheck passes them too.
  # Only running the function fails — which is why every explanation lives out
  # here and the substitution below is kept comment-free.
  #
  # The traps expand "$tmp" INTO the trap string (shellcheck's SC2064 case,
  # deliberately): `tmp` is a `local`, and an EXIT handler runs after the
  # shell begins unwinding, when that local is already gone — under `set -u`
  # the handler would then fail and take the exit status with it.
  # shellcheck disable=SC2064
  why="$(
    trap "rm -f '$tmp'" EXIT
    trap "rm -f '$tmp'; exit 130" HUP INT TERM
    rc=0
    curl -q --proto '=https' --proto-redir '=https' --tlsv1.2 \
         --fail --silent --show-error --location --max-redirs 3 \
         --connect-timeout 5 --max-time 10 --max-filesize "$max" \
         --output "$tmp" "$url" || rc=$?
    bytes="$(wc -c < "$tmp" | tr -d '[:space:]')"
    prefix="$(head -c 512 "$tmp" | tr -d '[:space:]')"
    if [ "$rc" -ne 0 ]; then
      printf 'curl exited %s' "$rc"
    elif [ ! -s "$tmp" ]; then
      printf 'the response was empty'
    elif [ "$bytes" -gt "$max" ]; then
      printf 'the body is %s bytes, too large for a release record (cap %s)' "$bytes" "$max"
    elif [ "${prefix#\{}" != "$prefix" ]; then
      cat "$tmp" > "$dest" || printf 'the body could not be written to %s' "$dest"
    else
      printf 'the body does not begin with a JSON object, so it is not a release record (an error page, a captive portal, or a redirect target)'
    fi
  )" || sub=$?

  # An interrupted or killed subshell prints no reason at all, so its exit
  # status is checked too — otherwise "no reason" would read as success.
  if [ -z "$why" ] && [ "$sub" -ne 0 ]; then
    why="the download ended abnormally (exit $sub)"
  fi
  if [ -z "$why" ] && [ ! -s "$dest" ]; then
    why='nothing was written'
  fi

  if [ -n "$why" ]; then
    log "WARNING: could not fetch ${tag}'s release record from $safe_url ($why). Its pairing and any digest pin on it stay UNVERIFIED, exactly as they were before this fetch existed — an absent record predicts nothing about the images. To see why by hand (credentials masked): curl -q --proto '=https' --tlsv1.2 --fail --location --max-time 10 '$safe_url'"
    return 1
  fi
  RECORD_FETCHED_FROM="$safe_url"
  bytes="$(wc -c < "$dest" | tr -d '[:space:]')"
  log "fetched ${tag}'s release record from $safe_url ($bytes bytes) — re-checking the pinned triple against it"
  return 0
}

# release_mapping_check ROOT MODE CORE USER SEARCH — hold the tag triple a run
# is about to use against releases/<tag>.json, via deploy/release-mapping.py.
# Returns 0 to continue (verified, or UNVERIFIED with the checker's WARNING
# already printed) and 1 to stop; the caller owns the die message, because
# only the caller knows what "nothing was changed" covers at its call site.
#
# THE GAP THIS CLOSES. The three VIDRA_*_TAG values are independent strings,
# and until this check nothing asked whether they had ever been released
# TOGETHER: a vidra-user tag from another release, or a core/search pairing
# never released together, was dumped, pulled, migrated and started. Tags are
# passed in already resolved by env_get (or rollback's target), so the checker
# judges exactly the triple the checkout sync and compose will use rather than
# re-deriving it with a second parser.
#
# THE TREE'S OWN RELEASE. deploy/release.sh tags this repository BEFORE any
# image exists, so a tree at tag vN (pin-release.sh's output, or the unpacked vN
# bundle) cannot contain releases/vN.json. The tags pointing at HEAD, or the
# bundle's own tag, are passed along so the checker can tell "this tree's own
# release, record not yet possible" (a WARNING) from "a release this tree knows
# nothing about" (a refusal in deploy mode). `git tag --points-at` only READS
# the checkout; a failure there just forfeits that allowance.
#
# What the tree cannot prove is then FETCHED: see the second pass at the bottom
# of this function, which downloads that record and asks the checker again. So
# the newest release is compared by tag string only on a host that cannot
# reach the record — offline, or in the window before the record PR merges,
# when it does not exist anywhere yet. That last case closes only when the
# record ships inside the release artifact.
#
# Exit 3 is the checker's UNVERIFIED code; see the header of
# deploy/release-mapping.py for the full contract.
release_mapping_check() {
  local root="$1" mode="$2" rc=0 t tags override wanted='' record_dir rc2
  # The image source goes along with the tags, resolved the same way: the
  # compose file pulls ${VIDRA_IMAGE_REGISTRY:-ghcr.io}/${VIDRA_IMAGE_OWNER:-yegamble}/<repo>,
  # and a record can only vouch for the images at ITS repository. A fork or a
  # mirror is reported UNVERIFIED, never refused.
  local -a args=(check --mode "$mode" --releases "$root/releases" --env "$ENV_FILE"
    --core "$3" --user "$4" --search "$5"
    --registry "$(env_get VIDRA_IMAGE_REGISTRY '')" --owner "$(env_get VIDRA_IMAGE_OWNER '')")
  # Named here rather than left to python3's "can't open file", which the
  # caller's message would otherwise present as a verdict about the tags.
  if [ ! -f "$root/deploy/release-mapping.py" ]; then
    printf '[release-mapping] ERROR: deploy/release-mapping.py is missing from %s, so the pinned tags cannot be checked. This tree is incomplete or mixes revisions. Take deploy/release-mapping.py and releases/ from the same revision as deploy/lib.sh.\n' "$root" >&2
    return 1
  fi
  # VIDRA_RELEASE_MAPPING=warn — the operator's override for a DEPLOY of a
  # triple no record pairs (a release whose record has not landed on this tree
  # yet, a rehearsal lab; a rollback already warns there). Read through env_get
  # so it works from the process environment and the env file alike, exactly
  # like VIDRA_SKIP_DNS_PREFLIGHT. It never reaches past the pairing: a digest
  # that contradicts a record, a tag that cannot be parsed, a broken releases/
  # and a stale bundle predict a real failure and still stop the run. An
  # unrecognised value is reported and IGNORED rather than refused: a typo then
  # neither bypasses the check silently (the normal verdict applies) nor stops
  # a rollback on its own.
  override="$(env_get VIDRA_RELEASE_MAPPING '')"
  case "$override" in
    warn)
      printf '[release-mapping] WARNING: VIDRA_RELEASE_MAPPING=warn is set — a tag triple no record pairs will WARN instead of stopping this run. A digest that contradicts a record, a tag that cannot be parsed, a broken releases/ directory and a stale bundle still stop it. Unset it once releases/ records this pairing.\n' >&2
      args+=(--unrecorded warn) ;;
    ''|refuse) ;;
    *)
      printf '[release-mapping] WARNING: VIDRA_RELEASE_MAPPING=%s is not a value this check knows (warn, or unset) and was ignored; the normal verdict applies.\n' "$override" >&2 ;;
  esac
  if is_bundle_tree "$root"; then
    args+=(--bundle-manifest "$root/vidra-bundle.manifest")
  elif command -v git >/dev/null 2>&1; then
    # `git tag --points-at` only READS the checkout. A failure (a dubious-
    # ownership refusal, a root that is not a repository) is logged rather
    # than swallowed: it forfeits the tree's-own-release allowance, and a
    # refusal that follows must read as that, not as a verdict about the
    # tags. VIDRA_RELEASE_MAPPING=warn is the way past it mid-incident.
    if tags="$(git -C "$root" tag --points-at HEAD 2>&1)"; then
      while IFS= read -r t; do
        if [ -n "$t" ]; then
          args+=(--tree-tag "$t")
        fi
      done <<EOF
$tags
EOF
    else
      log "could not read tags at HEAD ($(printf '%s' "$tags" | head -n1)); the tree's-own-release allowance is forfeited"
    fi
  fi
  python3 "$root/deploy/release-mapping.py" "${args[@]}" || rc=$?

  # THE SECOND PASS — the record this tree CANNOT carry.
  #
  # Pass 1 above is untouched, and its verdict is the FLOOR: the second pass
  # may only ever replace it with one reached using a record that actually
  # loaded. release.sh tags this repository before any image, and so any
  # digest, exists, so releases/vN.json is written after the publish and lands
  # on main in a PR — a vN tree carries records only up to v(N-1), and the
  # pairing and any digest pin on vN were compared against nothing at all.
  #
  # WHICH RELEASE TO FETCH IS THE CHECKER'S ANSWER, not a rule re-derived
  # here. `--print-missing-release` prints the newest of the three pinned tags
  # when the verdict turns on that record being absent, and nothing otherwise
  # (a recorded triple, a release older than every record, an unparseable
  # tag). The first cut of this asked for the CORE tag on rc==3 only, which
  # was wrong twice over: v0.7.4 and v0.7.5 re-released vidra-core ALONE, so
  # their triples are not uniform, pass 1 answers REFUSED (1) rather than
  # UNVERIFIED (3), and no fetch was attempted at all — the operator's only
  # route past the two newest releases was the blanket
  # VIDRA_RELEASE_MAPPING=warn override, with the proving record one GET away.
  #
  # An OLDER release-mapping.py does not know the flag, exits 2 and prints
  # nothing, so `wanted` is empty and nothing is fetched. That is the correct
  # degradation and it is not hypothetical: the beta host is a hand-patched
  # NO-GIT bundle tree, where a new lib.sh beside an older checker is a state
  # that really occurs.
  if [ "$rc" -ne 0 ]; then
    wanted="$(python3 "$root/deploy/release-mapping.py" "${args[@]}" --print-missing-release 2>/dev/null | tr -d '\r\n')" || wanted=''
  fi
  if [ -n "$wanted" ] && [ ! -f "$root/releases/$wanted.json" ]; then
    # A directory, so the file can carry the name the checker validates it by
    # (<release>.json), and one `rm -rf` cleans up every path below.
    # Same convention as the download's own temp file. A BARE `mktemp -d`
    # ignores TMPDIR on BSD — measured: with TMPDIR exported it still made the
    # directory under /var/folders — so half of this feature honoured the
    # operator's choice of scratch space and half did not.
    record_dir="$(mktemp -d "${TMPDIR:-/tmp}/vidra-record.XXXXXX" 2>/dev/null)" || record_dir=''
    if [ -z "$record_dir" ]; then
      log "could not create a temporary directory, so ${wanted}'s release record was not fetched; the verdict above stands"
    else
      # THE WHOLE SECOND PASS RUNS IN A SUBSHELL THAT OWNS THE DIRECTORY, for
      # the same reason the download owns its file: lib.sh is SOURCED, so a
      # `trap ... EXIT` at function scope would replace the caller's. Ctrl-C
      # during the re-check used to leave the directory (and the record in it)
      # behind. A plain ( ) subshell, unlike $( ), passes stdout and stderr
      # straight through, so every line below still reaches the operator live.
      #
      # The verdict comes back as the exit status:
      #   0|1|3  the re-check's verdict, reached with the record ADMITTED
      #   64     keep the first pass's verdict, unchanged
      #   130    interrupted
      (
        # The path is expanded INTO the trap string, not referenced from it.
        # `record_dir` is a `local`, and an EXIT trap runs after the shell has
        # started unwinding, by which point the local is gone: under `set -u`
        # the handler then died with "record_dir: unbound variable", and a
        # failed EXIT trap makes the subshell exit 1 — which this function
        # read as the checker's REFUSED. A cleanup bug became a fabricated
        # refusal, on every path through the second pass.
        # shellcheck disable=SC2064  # expanding now is the point, see above
        trap "rm -rf '$record_dir'" EXIT
        # shellcheck disable=SC2064
        trap "rm -rf '$record_dir'; exit 130" HUP INT TERM
        fetch_release_record "$wanted" "$record_dir/$wanted.json" || exit 64
        log "the verdict above was reached before that record was available — the one below supersedes it"
        rc2=0
        python3 "$root/deploy/release-mapping.py" "${args[@]}" \
          --extra-record "$record_dir/$wanted.json" \
          > "$record_dir/out" 2> "$record_dir/err" || rc2=$?
        cat "$record_dir/out"
        cat "$record_dir/err" >&2
        # THE VERDICT MAY ONLY MOVE ON A RECORD THAT WAS USED. Two guards, and
        # the pass-1 verdict survives both failing:
        #   * the checker must SAY it admitted the record. The marker is printed
        #     on stdout, where no text from the fetched record can appear
        #     (record content only ever reaches warnings and errors, on stderr),
        #     so a crafted body cannot forge it.
        #   * the exit must be one this contract defines. `rc` used to be
        #     reassigned unconditionally, so argparse's exit 2 from an older
        #     checker — or any crash — fell through to `return 1` and KILLED a
        #     deploy pass 1 had allowed. A feature that can only ever ADD
        #     verification must not be able to subtract a deploy.
        if ! grep -q '^\[release-mapping\] extra-record-admitted ' "$record_dir/out"; then
          log "WARNING: the re-check ended $rc2 without using ${wanted}'s fetched record, so the verdict above stands unchanged."
          exit 64
        fi
        case "$rc2" in
          1)
            # D4. A wrong — or forged — remote record must never trap an
            # operator mid-incident with no way out but reading this source.
            # BOTH knobs are named because one is not enough: turning the
            # fetch off falls back to the tree alone, which can never report
            # verified for a release it has no record for, and for a
            # core-only triple (v0.7.4, v0.7.5) the pairing refusal then
            # stands. Measured, not assumed.
            log "WARNING: this stop rests on the record FETCHED from $RECORD_FETCHED_FROM, not on anything in this tree. If that record is wrong, or you cannot reach a copy you trust, re-run with VIDRA_RECORD_FETCH=off. That falls back to this tree alone, which can NEVER report verified for a release the tree has no record for: a UNIFORM vN triple then continues UNVERIFIED with a warning, but a triple the tree cannot pair — a core-only release such as v0.7.4/v0.7.5 — is still REFUSED by the pairing check, and VIDRA_RELEASE_MAPPING=warn is the override that waives that check for one run. Neither knob makes this report verified."
            exit 1 ;;
          0|3)
            log "the verdict above rests on the record fetched from $RECORD_FETCHED_FROM, not on anything in this tree"
            exit "$rc2" ;;
          *)
            log "WARNING: the re-check with ${wanted}'s fetched record ended $rc2, which is not a verdict this check knows (an older deploy/release-mapping.py, or a crash). It was IGNORED and the verdict above stands unchanged."
            exit 64 ;;
        esac
      )
      rc2=$?
      case "$rc2" in
        64) ;;   # the first pass's verdict stands, and it is already in `rc`
        130)
          # Interrupted before anything mutated. Stopping is the honest
          # answer: continuing would deploy on a preflight nobody finished.
          log "the release-record re-check was interrupted — nothing was changed"
          rc=1 ;;
        *) rc="$rc2" ;;
      esac
      rm -rf "$record_dir"
    fi
  fi

  case "$rc" in
    0) return 0 ;;
    3) log "release mapping NOT verified (WARNING above) — continuing"; return 0 ;;
  esac
  return 1
}
