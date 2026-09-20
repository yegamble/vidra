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
fetch_release_record() {
  local tag="$1" dest="$2" base url tmp bytes prefix why rc=0
  local max=262144   # 256 KiB. A record is ~2 KiB; anything near this is a page, not a record.

  # THE AIRGAPPED SWITCH, read through env_get so it works from the env file
  # and the process environment alike, exactly like VIDRA_SKIP_DNS_PREFLIGHT.
  # Checked FIRST, so a host that turned it off is never seen reaching out and
  # never pays the timeout. The word list mirrors is_true's, and for the same
  # reason: env files are hand-edited and "no" gets typed several ways.
  case "$(env_get VIDRA_RECORD_FETCH '')" in
    off|OFF|Off|0|false|FALSE|False|no|NO|No)
      log "VIDRA_RECORD_FETCH is off — not fetching ${tag}'s release record. This run verifies only what the tree itself can prove."
      return 1 ;;
  esac

  # STRICT SEMVER BEFORE ANYTHING IS INTERPOLATED. The tag comes from
  # VIDRA_CORE_TAG in an operator-edited env file and goes into BOTH a URL and
  # a filename, so `v1.2.3/../../evil`, `v1.2.3?ref=x` and `v1.2.3 v1.2.4` must
  # be stopped before either. Releases are only ever cut as vMAJOR.MINOR.PATCH
  # (deploy/release.sh), so nothing legitimate is excluded: a prerelease a
  # rehearsal lab deploys has no record upstream to fetch in the first place.
  if ! grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+$' <<<"$tag"; then
    log "not fetching a release record: '$tag' is not a vMAJOR.MINOR.PATCH release tag, and only those have records."
    return 1
  fi

  # The fork/mirror knob, alongside VIDRA_IMAGE_REGISTRY/VIDRA_IMAGE_OWNER: a
  # fork publishes its own records, and an egress-filtered network mirrors them.
  base="$(env_get VIDRA_RECORD_BASE_URL 'https://raw.githubusercontent.com/yegamble/vidra/main/releases')"
  base="${base%/}"
  # HTTPS ONLY, here as well as in curl's own --proto below. This record decides
  # what the deploy will verify, so a channel anyone on the path can rewrite is
  # worse than no record at all. Named here rather than left to a curl error, so
  # the message says which key to fix.
  case "$base" in
    https://*) ;;
    *)
      log "not fetching a release record: VIDRA_RECORD_BASE_URL=$base is not an https:// URL, and this record decides what the deploy verifies."
      return 1 ;;
  esac
  url="$base/$tag.json"

  if ! command -v curl >/dev/null 2>&1; then
    log "not fetching a release record: curl is not installed on this host. ${tag}'s pairing and digests stay unverified; install curl, or fetch $url by hand onto this tree as releases/${tag}.json."
    return 1
  fi

  # Into a TEMP FILE, never straight to DEST: a truncated, oversized or HTML
  # body must not end up at the path the checker is then pointed at. One
  # cleanup point below covers every outcome.
  tmp="$(mktemp "${TMPDIR:-/tmp}/vidra-record.XXXXXX" 2>/dev/null)" || tmp=''
  if [ -z "$tmp" ]; then
    log "not fetching a release record: could not create a temporary file."
    return 1
  fi

  # --proto/--proto-redir pin TLS across redirects as well as on the first hop;
  # --max-time bounds a black-holed host (this runs in preflight, before
  # anything has changed, and must not turn a deploy into a hang);
  # --max-filesize refuses an oversized body at the wire, and the byte count
  # below catches a chunked response that declares no length.
  curl --proto '=https' --proto-redir '=https' --tlsv1.2 \
       --fail --silent --show-error --location \
       --max-time 10 --max-filesize "$max" \
       --output "$tmp" "$url" || rc=$?

  why=''
  if [ "$rc" -ne 0 ]; then
    why="curl exited $rc"
  elif [ ! -s "$tmp" ]; then
    why='the response was empty'
  else
    bytes="$(wc -c < "$tmp" | tr -d '[:space:]')"
    prefix="$(head -c 512 "$tmp" | tr -d '[:space:]')"
    if [ "$bytes" -gt "$max" ]; then
      why="the body is $bytes bytes, too large for a release record (cap $max)"
    else
      case "$prefix" in
        \{*) cat "$tmp" > "$dest" || why="the body could not be written to $dest" ;;
        *) why='the body does not begin with a JSON object, so it is not a release record (an error page, a captive portal, or a redirect target)' ;;
      esac
    fi
  fi
  rm -f "$tmp"

  if [ -n "$why" ]; then
    log "WARNING: could not fetch ${tag}'s release record from $url ($why). Its pairing and any digest pin on it stay UNVERIFIED, exactly as they were before this fetch existed — an absent record predicts nothing about the images. To see why by hand: curl --proto '=https' --tlsv1.2 --fail --location --max-time 10 '$url'"
    return 1
  fi
  log "fetched ${tag}'s release record from $url ($bytes bytes) — re-checking the pinned triple against it"
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
  local root="$1" mode="$2" rc=0 t tags override core_tag record_dir
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
  # Pass 1 above is untouched. It answers UNVERIFIED (3) for a uniform triple
  # newer than every record, which is every deploy of the NEWEST release:
  # release.sh tags this repository before any image, and so any digest,
  # exists, so releases/vN.json is written after the publish and lands on main
  # in a PR. Until now that verdict was the end of it — the pairing and any
  # digest pin on vN were compared against nothing at all.
  #
  # So: when pass 1 is UNVERIFIED and this tree genuinely has no record for the
  # core tag, fetch that record and ASK AGAIN with it. Both conditions matter.
  # The rc gate keeps this off every ordinary deploy and out of the way of
  # every refusal (a mixed triple is already REFUSED at 1 and never reaches
  # here). The file test keeps it off the path where the tree can answer for
  # itself, so the common case makes no request at all.
  #
  # The digest pin is what this buys, and it is worth being precise about how
  # much: deploy.sh's require_embedded_migrate_tag refuses a `tag@sha256:...`
  # spelling for VIDRA_CORE_TAG and VIDRA_SEARCH_TAG before this runs, so the
  # digest comparison is reachable today only for VIDRA_USER_TAG. The pairing
  # assertion applies to all three. Pulling by the recorded digests stays a
  # separate follow-up (see releases/README.md).
  #
  # Severity is unchanged from what absence has always meant: a fetch that
  # fails leaves rc at 3 and the run continues, in a deploy and a rollback
  # alike. Only a record that LOADS and CONTRADICTS the pins turns this into a
  # 1 — that is the one outcome predicting the wrong bytes on disk.
  core_tag="${3%%@*}"
  if [ "$rc" -eq 3 ] && [ ! -f "$root/releases/$core_tag.json" ]; then
    # A directory, so the file can carry the name the checker validates it by
    # (<release>.json), and one `rm -rf` cleans up every path below.
    record_dir="$(mktemp -d 2>/dev/null)" || record_dir=''
    if [ -z "$record_dir" ]; then
      log "could not create a temporary directory, so ${core_tag}'s release record was not fetched; the WARNING above stands"
    else
      if fetch_release_record "$core_tag" "$record_dir/$core_tag.json"; then
        log "the WARNING above was printed before that record was available — the verdict below supersedes it"
        rc=0
        python3 "$root/deploy/release-mapping.py" "${args[@]}" \
          --extra-record "$record_dir/$core_tag.json" || rc=$?
      fi
      rm -rf "$record_dir"
    fi
  fi

  case "$rc" in
    0) return 0 ;;
    3) log "release mapping NOT verified (WARNING above) — continuing"; return 0 ;;
  esac
  return 1
}
