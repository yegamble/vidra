#!/usr/bin/env bash
#
# One-command install of a Vidra deployment host.
#
#   curl -fsSL https://raw.githubusercontent.com/yegamble/vidra/main/install.sh | sh
#   curl -fsSL https://raw.githubusercontent.com/yegamble/vidra/main/install.sh | sh -s -- --yes
#   sh install.sh --dir /srv/vidra --ref v0.3.0
#
# In order: detect the platform; install git, curl, Docker Engine and the Compose
# v2 plugin when they are missing (Debian/Ubuntu apt only); resolve the release to
# pin; clone this meta-repo into /opt/vidra and run ./bootstrap.sh for the three
# component checkouts; download the `vidra` operator CLI from vidra-core's release
# assets and verify its checksum; then hand over to `vidra setup`, the interview
# that writes env/production.env and deploy/Caddyfile.local.
#
# It is IDEMPOTENT and RESUMABLE. Every step states what it found and skipped, and
# a second run of a completed install changes nothing. If it dies halfway - no
# release assets, a checksum mismatch, a missing answer - the tree it has already
# created stays exactly where it is and re-running picks up from there.
#
# ---------------------------------------------------------------------------
# WHY IT CLONES, when the worklist item asks for "no git clone"
#
# Because three things in this repo need a real git checkout, today:
#
#   1. docker-compose.yml `include:`s ./vidra-core/docker-compose.yml. The
#      production model does not exist without that file on disk - a tarball of
#      the meta-repo alone renders nothing.
#   2. vidra-core/deploy/media/nginx.conf.template is BIND-MOUNTED by the media
#      profile. A missing bind-mount source is created by Docker as a directory
#      and the container crash-loops on it.
#   3. deploy/deploy.sh computes the expected schema version from
#      `ls vidra-core/migrations/*.up.sql` and syncs the component checkouts to
#      the deployed tags - both need the .git directories, not just the files.
#
# So what is actually delivered is "no MANUAL git": the operator types no git
# command and knows no repository layout. The installer drives git itself, and
# bootstrap.sh - which already exists, is already idempotent, and is already the
# thing CI exercises - clones the components. Making the install git-free is a
# change to the compose model, not to this script, and it is not worth pretending
# otherwise here.
#
# WHY IT STOPS AT `vidra setup`
#
# The remaining answers are the operator's and nobody else's: the domain, whether
# its DNS already points at this host, S3 credentials, SMTP. Worse, the first
# `up -d` ORDERS A TLS CERTIFICATE, and an unattended deploy against a domain
# that does not resolve here yet spends Let's Encrypt rate limit on a failure.
# The web setup wizard (phase-1 item 9) does not exist yet either, so there is no
# URL to print - the terminal interview is the wizard, and this script's last act
# is to run it with a terminal attached.
#
# WHAT IT NEVER DOES, deliberately:
#
#   * write or overwrite env/production.env itself. That file holds the KEKs that
#     seal MFA/federation/ATProto data in the database; re-minting them orphans
#     everything already sealed. `vidra setup` owns the file, refuses to rewrite
#     an existing one without --yes, and this script never passes --yes to it.
#     "Re-run the installer" must never cost an instance its secrets.
#   * `docker compose up` anything. Deploying is deploy/deploy.sh's job, with its
#     pre-deploy dump, its migrator-tag floor and its health gates.
#   * open a port or touch sshd. deploy/provision.sh does not do that either, for
#     the reasons it explains at length; a cloud firewall outside the box is the
#     only control Docker cannot bypass.
#
# ---------------------------------------------------------------------------

set -eu

# `pipefail` is a bash/ksh option that POSIX does not require, and /bin/sh on a
# Debian or Ubuntu host - the shell a `curl ... | sh` install actually runs on - is
# dash, which only grew it recently. Asking for it in a subshell first is the
# difference between "the option is on" and "the install died before printing
# anything, with a syntax error, on the one line that was supposed to make it
# careful". Nothing below depends on it for correctness; it is a second net.
if (set -o pipefail) 2>/dev/null; then
  set -o pipefail
fi

log()  { printf '[install] %s\n' "$*"; }
die()  { printf '[install] ERROR: %s\n' "$*" >&2; exit 1; }
step() { printf '\n[install] ===== %s =====\n' "$*"; }

# Warnings are collected and reprinted at the end, exactly as deploy/provision.sh
# does it: an install scrolls several screens and the things an operator must not
# miss are precisely the ones that scrolled past.
WARNINGS=""
warn() {
  printf '[install] WARNING: %s\n' "$*" >&2
  WARNINGS="${WARNINGS}  * $*
"
}

usage() {
  cat <<'EOF'
usage: curl -fsSL https://raw.githubusercontent.com/yegamble/vidra/main/install.sh | sh
       curl -fsSL https://raw.githubusercontent.com/yegamble/vidra/main/install.sh | sh -s -- [flags]
       sh install.sh [flags]

Installs a Vidra deployment host: Docker + Compose (>= 2.24) if missing, this
meta-repo and its three component checkouts in the install directory, the `vidra`
operator CLI in /usr/local/bin, and then the `vidra setup` interview.

It never writes env/production.env itself and never overwrites one that exists:
that file holds the KEKs sealing data in the database, and re-running an
installer must not cost an instance its secrets. Deploying is a separate,
deliberate step (`vidra deploy`).

Advanced users can skip all of this: deploy/README.md documents the manual path,
and every step below is one of its commands.

flags:
  -y, --yes            do not ask for confirmation before installing anything.
                       Required for an unattended install; without it, and
                       without a terminal to ask on, this script refuses.
      --ref <tag>      release to pin: the three component checkouts and the
                       vidra CLI all come from it (default: vidra-core's latest
                       release). A release cut before the release-assets workflow
                       landed carries no CLI binary and is refused with the
                       `make build-vidra` fallback named.
      --dir <path>     absolute path to install into (default /opt/vidra)
      --owner <owner>  GitHub owner to clone from, for a fork (default yegamble)
  -h, --help           this text

environment (the flags win when both are given):
  VIDRA_YES=1          same as --yes
  VIDRA_REF=<tag>      same as --ref
  VIDRA_HOME=<path>    same as --dir
  VIDRA_GH_OWNER=<o>   same as --owner

exit status: 0 when the install completed (including the macOS "wrong platform,
here is the dev path" case), non-zero when it stopped and said why. Whatever it
had already created is left in place: re-run it.
EOF
}

# --- arguments ------------------------------------------------------------------
# Parsed FIRST, before any platform or privilege check, so `--help` answers on any
# machine, offline, as an unprivileged user. meta-ci runs exactly that as a smoke
# test.
OWNER="${VIDRA_GH_OWNER:-yegamble}"
DIR="${VIDRA_HOME:-/opt/vidra}"
REF="${VIDRA_REF:-}"
ASSUME_YES=0
case "${VIDRA_YES:-}" in
  ""|0|false|no|off) ;;
  *) ASSUME_YES=1 ;;
esac

need_value() {
  # $1 = flag name, $2 = how many arguments are left including the flag itself
  [ "$2" -ge 2 ] || die "$1 needs a value (see --help)"
}

while [ $# -gt 0 ]; do
  case "$1" in
    -y|--yes)   ASSUME_YES=1; shift ;;
    --ref)      need_value --ref "$#";   REF="$2";   shift 2 ;;
    --ref=*)    REF="${1#--ref=}";       shift ;;
    --dir)      need_value --dir "$#";   DIR="$2";   shift 2 ;;
    --dir=*)    DIR="${1#--dir=}";       shift ;;
    --owner)    need_value --owner "$#"; OWNER="$2"; shift 2 ;;
    --owner=*)  OWNER="${1#--owner=}";   shift ;;
    -h|--help)  usage; exit 0 ;;
    --)         shift; break ;;
    *)          usage >&2; die "unknown argument: $1" ;;
  esac
done
[ $# -eq 0 ] || { usage >&2; die "unexpected argument: $1"; }

# All three end up inside a URL or a shell word. Validated here rather than at
# first use, because the failure otherwise arrives as a curl error about a
# hostname nobody typed.
case "$OWNER" in
  ""|*[!A-Za-z0-9._-]*) die "--owner must be a GitHub owner name (got '${OWNER}')" ;;
esac
case "$REF" in
  *[!A-Za-z0-9._/+-]*) die "--ref must be a release tag such as v0.3.0 (got '${REF}')" ;;
esac
case "$DIR" in
  /*) ;;
  *) die "--dir must be an absolute path (got '${DIR}') - an install directory relative to wherever curl happened to run is not a location anyone can find again" ;;
esac

# --- 1/7 platform ----------------------------------------------------------------
step "1/7 platform"
OS="$(uname -s)"
case "$OS" in
  Linux) ;;
  Darwin)
    # Not an error, and not a thing to work around: a deployment is Linux + Docker
    # + systemd, and macOS is where the DEVELOPMENT stack runs. Say which is which
    # and change nothing.
    cat <<EOF

[install] This is a SERVER installer and this is macOS, so it has done nothing.

  To run Vidra locally for development, the repo's own quick start is three
  commands (README.md "Quick start"):

      git clone https://github.com/${OWNER}/vidra.git && cd vidra
      make dev
      cd vidra-user && npm ci && NEXT_PUBLIC_API_BASE_URL=http://localhost:8080 npm run dev

  To DRIVE a deployment that runs somewhere else, install just the CLI: every
  release cut since vidra-core's release-assets workflow landed carries
  darwin/amd64 and darwin/arm64 builds of it at
  https://github.com/${OWNER}/vidra-core/releases , and 'vidra -C <checkout>'
  works against any deployment directory.

EOF
    exit 0
    ;;
  *)
    die "unsupported platform '${OS}'. This installer is apt + systemd + Docker on Linux; deploy/README.md documents every step it takes, so follow 'Host prerequisites' and 'First bring-up' by hand."
    ;;
esac

MACHINE="$(uname -m)"
case "$MACHINE" in
  x86_64|amd64)   ARCH=amd64 ;;
  aarch64|arm64)  ARCH=arm64 ;;
  *) die "unsupported architecture '${MACHINE}'. The published vidra CLI binaries are linux/amd64 and linux/arm64; build one for this machine with 'make build-vidra' in a vidra-core checkout and follow deploy/README.md by hand." ;;
esac
log "linux/${ARCH}"

# --- 2/7 privileges --------------------------------------------------------------
step "2/7 privileges"
# apt, ${DIR} under /opt and /usr/local/bin all need root. Which of those are
# actually reached depends on what is already installed, but the ANSWER to "can
# this script become root" does not - so it is settled here, once, before
# anything has been half-done.
AS_ROOT_PREFIX=""
if [ "$(id -u)" -eq 0 ]; then
  log "running as root"
else
  command -v sudo >/dev/null 2>&1 \
    || die "not root and no sudo. This installs packages, writes ${DIR} and puts a binary in /usr/local/bin - re-run as root ('sudo sh install.sh'), or follow deploy/README.md 'Host prerequisites' by hand."
  AS_ROOT_PREFIX="sudo"
  log "not root - apt, ${DIR} and /usr/local/bin will go through sudo (it may ask for your password)"
fi

as_root() {
  if [ -n "$AS_ROOT_PREFIX" ]; then
    sudo "$@"
  else
    "$@"
  fi
}

# --- 3/7 survey ------------------------------------------------------------------
# READ-ONLY. Everything that changes this machine happens after the confirmation
# below, and the confirmation can only state the plan if the plan is known first.
step "3/7 what is already here"

have_tty() {
  # Opening /dev/tty is the only honest test: [ -t 0 ] is false for every
  # `curl ... | sh` (stdin is the pipe) while the terminal is still right there,
  # and [ -r /dev/tty ] is true on a host with no controlling terminal at all.
  #
  # In a SUBSHELL, and with `true` rather than `:`, because both details are
  # load-bearing under dash - the /bin/sh a piped install actually runs on. A
  # redirection that fails on a POSIX *special* built-in (`:` is one, `true` is
  # not) makes a non-interactive shell exit outright, so the obvious spelling of
  # this test terminated the whole installer with status 2 and no message on
  # exactly the headless host it exists to detect. Verified in a container.
  ( true < /dev/tty ) 2>/dev/null
}

MISSING_PKGS=""
want_pkg() {
  case " $MISSING_PKGS " in
    *" $1 "*) ;;
    *) MISSING_PKGS="${MISSING_PKGS} $1" ;;
  esac
}

for tool in git curl; do
  if command -v "$tool" >/dev/null 2>&1; then
    log "${tool}: present"
  else
    log "${tool}: MISSING - will apt-get install it"
    want_pkg "$tool"
  fi
done

# The Compose floor, parsed exactly as deploy/deploy.sh's require_compose_version
# parses it (and rollback.sh, and restore.sh). Same string, same split, same
# refusal - a fourth interpretation of "is this Compose new enough" is a fourth
# chance to disagree with the scripts that actually gate the deploy.
compose_at_least_2_24() {
  local v major minor
  v="${1#v}"
  major="${v%%.*}"
  minor="${v#*.}"; minor="${minor%%.*}"
  case "${major}.${minor}" in
    *[!0-9.]*|.*|*.) return 2 ;;
  esac
  if [ "$major" -gt 2 ]; then return 0; fi
  if [ "$major" -eq 2 ] && [ "$minor" -ge 24 ]; then return 0; fi
  return 1
}

INSTALL_DOCKER=0
COMPOSE_VERSION=""
if command -v docker >/dev/null 2>&1; then
  # `docker compose version` asks the CLI plugin, not the daemon, so this works
  # without the docker group and without sudo - which matters, because a sudo
  # password prompt during a survey step is indistinguishable from a hang.
  COMPOSE_VERSION="$(docker compose version --short 2>/dev/null || true)"
  if [ -z "$COMPOSE_VERSION" ]; then
    log "docker: present, but 'docker compose version' does not work - will install the docker-compose-plugin package"
    want_pkg docker-compose-plugin
  else
    if compose_at_least_2_24 "$COMPOSE_VERSION"; then
      log "docker compose: ${COMPOSE_VERSION} (>= 2.24)"
    else
      # Refuse rather than upgrade: an existing Docker on a host somebody else
      # set up is not this script's to replace, and the fix is one apt command.
      die "docker compose ${COMPOSE_VERSION} is too old - docker-compose.prod.yml uses the !reset/!override merge tags (Compose >= 2.24) and an older Compose IGNORES them silently, leaving Postgres and Redis published on 0.0.0.0. deploy/deploy.sh refuses the same version for the same reason. Upgrade the plugin first: 'apt-get install --only-upgrade docker-compose-plugin' (see deploy/README.md, 'Host prerequisites' -> 'Docker'), then re-run this installer."
    fi
  fi
else
  log "docker: MISSING - will install Docker Engine + the Compose plugin from Docker's own apt repository"
  INSTALL_DOCKER=1
fi

# What state is the install directory in? Three cases, and only one of them is a
# refusal.
DIR_STATE=fresh
if [ -d "${DIR}/.git" ]; then
  DIR_STATE=checkout
  log "${DIR}: an existing git checkout - will fetch and fast-forward it if it is clean"
elif [ -e "$DIR" ] && [ -n "$(ls -A "$DIR" 2>/dev/null || true)" ]; then
  die "${DIR} exists, is not a git checkout, and is not empty. Refusing to clone over somebody's files - move it aside, or pass --dir <another path>."
else
  log "${DIR}: will be created and cloned into"
fi

# The release everything gets pinned to. ONE tag for the three component
# checkouts AND the CLI: the release scripts cut all three component repos under
# one version, and a host running the compose files of one release with the
# binaries of another is a configuration nobody has ever tested.
#
# The GitHub REST API, read with curl and cut with sed. jq is deliberately NOT a
# dependency: it is not on a fresh droplet, and an installer that apt-installs a
# JSON parser in order to read one string has lost the plot.
resolve_tag() {
  TAG="$(
    curl -fsSL -H 'Accept: application/vnd.github+json' \
      "https://api.github.com/repos/${OWNER}/vidra-core/releases/latest" 2>/dev/null \
      | grep -m 1 '"tag_name"' \
      | sed -e 's/.*"tag_name"[^"]*"//' -e 's/".*//' || true
  )"
  [ -n "$TAG" ] \
    || die "could not resolve the latest ${OWNER}/vidra-core release from the GitHub API (rate limit, no network, or no releases yet). Pass --ref <tag> to name one: https://github.com/${OWNER}/vidra-core/releases"
  log "release: ${TAG} (latest ${OWNER}/vidra-core release)"
}

# Resolved here, before the confirmation, ONLY when it can be: naming the tag in
# the prompt is worth a round-trip, but a host that does not have curl yet is the
# ordinary bare-droplet case and must not die on a lookup two steps before the
# step that installs the tool to do it with.
TAG=""
if [ -n "$REF" ]; then
  TAG="$REF"
  log "release: ${TAG} (pinned with --ref)"
elif command -v curl >/dev/null 2>&1; then
  resolve_tag
else
  log "release: the latest ${OWNER}/vidra-core release, looked up once curl is installed"
fi
TAG_SHOWN="${TAG:-<the latest release>}"

# --- confirmation ----------------------------------------------------------------
# ONE prompt, for everything. Same shape as deploy/provision.sh and
# deploy/release.sh: --yes for the scripted caller, a question for a human, and a
# refusal when there is neither.
#
# It is read from /dev/tty, not stdin, because under `curl ... | sh` stdin IS the
# script. That is also why the refusal below matters: `curl ... | sh </dev/null`,
# a cron job or a Docker build has no terminal at all, and silently installing
# Docker onto a host nobody is watching is exactly the wrong default.
if [ "$ASSUME_YES" -eq 1 ]; then
  log "--yes given - not prompting."
elif have_tty; then
  echo
  echo "About to install Vidra on this host:"
  if [ -n "$MISSING_PKGS" ]; then
    echo "  apt packages    ${MISSING_PKGS# }"
  fi
  if [ "$INSTALL_DOCKER" -eq 1 ]; then
    echo "  docker          Engine + CLI + buildx + compose plugin, from download.docker.com"
  fi
  case "$DIR_STATE" in
    fresh)    echo "  clone           https://github.com/${OWNER}/vidra.git -> ${DIR}" ;;
    checkout) echo "  update          ${DIR} (fast-forward only, and only while it is clean)" ;;
  esac
  echo "  components      ${DIR}/vidra-{core,user,search} pinned to ${TAG_SHOWN}"
  echo "  cli             ${TAG_SHOWN}'s vidra_${TAG_SHOWN}_linux_${ARCH} -> /usr/local/bin/vidra"
  echo "  then            'vidra setup' - the interview that writes env/production.env"
  echo
  echo "It starts nothing, opens no port, and never rewrites an existing env file."
  echo
  printf 'Type "install" to continue: '
  read -r answer < /dev/tty
  [ "$answer" = "install" ] || { echo "Aborted."; exit 1; }
else
  # Deliberately the same shape as the wizard's own refusal in
  # vidra-core/cmd/vidra/setup.go: the mode is knowable up front, so it is
  # answered up front, with both ways out named.
  die "stdin is not a terminal and /dev/tty cannot be opened, so there is nobody to ask before this installs Docker and writes ${DIR} - this is what an unattended 'curl ... | sh </dev/null' hits, and every question would fail at once. Either run it from a real terminal, or pass --yes: 'curl -fsSL <url> | sh -s -- --yes'."
fi

# --- 4/7 dependencies -------------------------------------------------------------
step "4/7 docker, git, curl"
if [ -n "$MISSING_PKGS" ] || [ "$INSTALL_DOCKER" -eq 1 ]; then
  command -v apt-get >/dev/null 2>&1 \
    || die "no apt-get - this installer's package steps target Debian and Ubuntu. Everything it would do is documented in deploy/README.md 'Host prerequisites'; install git, curl, Docker Engine >= 24 and the Compose v2 plugin (>= 2.24) with your package manager and re-run this script, which will then skip straight to the clone."
  export DEBIAN_FRONTEND=noninteractive
else
  log "nothing to install."
fi

if [ -n "$MISSING_PKGS" ]; then
  log "apt-get install${MISSING_PKGS}"
  as_root apt-get update -qq
  # Word-split on purpose: MISSING_PKGS is a list this script built out of a
  # fixed vocabulary, not an operator string.
  # shellcheck disable=SC2086
  as_root apt-get install -y -qq $MISSING_PKGS
fi

if [ "$INSTALL_DOCKER" -eq 1 ]; then
  # Docker's OWN apt repository, by the steps documented at
  # docs.docker.com/engine/install - and NOT `curl get.docker.com | sh`, which is
  # a second remote script executing as root inside the one the operator already
  # decided to trust. The distro's docker.io package is not an option either: it
  # is routinely below the Compose 2.24 floor the production overlay needs, which
  # would leave this installer refusing its own work.
  #
  # /etc/os-release is PARSED, not sourced. It is the file that decides which
  # repository gets added to this machine; sourcing it would run whatever is in
  # it as root, and reading two values does not need that power.
  [ -r /etc/os-release ] || die "no readable /etc/os-release, so which Docker apt repository to add is unknowable. Install Docker Engine >= 24 with the Compose v2 plugin by hand (docs.docker.com/engine/install) and re-run."
  DISTRO_ID="$(sed -n 's/^ID=//p' /etc/os-release | tr -d '"' | head -1)"
  CODENAME="$(sed -n 's/^VERSION_CODENAME=//p' /etc/os-release | tr -d '"' | head -1)"
  if [ -z "$CODENAME" ]; then
    CODENAME="$(sed -n 's/^UBUNTU_CODENAME=//p' /etc/os-release | tr -d '"' | head -1)"
  fi
  case "$DISTRO_ID" in
    ubuntu|debian) ;;
    *) die "Docker's apt repository is published for ubuntu and debian; this host says ID=${DISTRO_ID:-unknown}. Install Docker Engine >= 24 with the Compose v2 plugin the way your distribution documents (docs.docker.com/engine/install), then re-run this installer - it will find it and carry on." ;;
  esac
  [ -n "$CODENAME" ] \
    || die "/etc/os-release names no VERSION_CODENAME, so the Docker apt repository line cannot be written. Install Docker Engine >= 24 with the Compose v2 plugin by hand and re-run."

  log "adding Docker's apt repository for ${DISTRO_ID} ${CODENAME}"
  as_root apt-get update -qq
  as_root apt-get install -y -qq ca-certificates curl
  as_root install -m 0755 -d /etc/apt/keyrings
  curl -fsSL "https://download.docker.com/linux/${DISTRO_ID}/gpg" \
    | as_root tee /etc/apt/keyrings/docker.asc >/dev/null
  as_root chmod a+r /etc/apt/keyrings/docker.asc
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/%s %s stable\n' \
    "$(dpkg --print-architecture)" "$DISTRO_ID" "$CODENAME" \
    | as_root tee /etc/apt/sources.list.d/docker.list >/dev/null
  as_root apt-get update -qq
  log "installing Docker Engine and the Compose plugin"
  as_root apt-get install -y -qq \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  # `restart: unless-stopped` in the compose overlay does nothing at all if the
  # daemon itself does not come back after a reboot.
  #
  # /run/systemd/system, not `command -v systemctl`: the binary exists in plenty
  # of images and containers where systemd is not the running init, and the
  # directory is the canonical test for the difference. Either way this is a
  # WARNING and not a death - nothing later in this script talks to the daemon
  # (`docker compose version` asks the plugin), so refusing to finish the install
  # over it would trade a real problem for a bigger one.
  if [ -d /run/systemd/system ]; then
    as_root systemctl enable --now docker \
      || warn "'systemctl enable --now docker' failed. The daemon must start at boot or the stack does not come back after a reboot, whatever restart policy the containers carry. Check 'systemctl status docker'."
  else
    warn "systemd is not the init here, so the docker daemon was NOT enabled at boot. Start it however this system does - otherwise the stack does not come back after a reboot, whatever restart policy the containers carry."
  fi
fi

# Whatever route got us here - pre-installed, plugin added, or a fresh Engine -
# the floor is re-checked against what is now on the machine. The version that
# matters is the one that will run the deploy, not the one the survey saw.
COMPOSE_VERSION="$(docker compose version --short 2>/dev/null || true)"
[ -n "$COMPOSE_VERSION" ] \
  || die "'docker compose version' still does not work after the install step. deploy/deploy.sh needs Compose v2 >= 2.24; see deploy/README.md 'Host prerequisites' -> 'Docker'."
compose_at_least_2_24 "$COMPOSE_VERSION" \
  || die "docker compose ${COMPOSE_VERSION} is below the 2.24 floor the production overlay needs (it ignores !reset/!override silently and leaves Postgres and Redis on 0.0.0.0). Upgrade docker-compose-plugin and re-run."
log "docker compose ${COMPOSE_VERSION}"

if [ -n "$AS_ROOT_PREFIX" ] && ! id -nG 2>/dev/null | tr ' ' '\n' | grep -qx docker; then
  warn "$(id -un) is not in the 'docker' group, so 'vidra deploy', 'vidra status' and every docker command will need sudo. Add it ('sudo usermod -aG docker $(id -un)') and log in again, or let 'sudo ./deploy/provision.sh' create the 'vidra' service user it puts in that group. Being in the docker group is root-equivalent - that is why neither script does it silently."
fi

# The lookup the survey could not do because curl was not installed yet.
if [ -z "$TAG" ]; then
  resolve_tag
fi

# --- 5/7 the deployment tree ------------------------------------------------------
step "5/7 the deployment tree"
if [ "$DIR_STATE" = "checkout" ]; then
  # NEVER reset, never discard, never stash. A checkout on a deployment host may
  # legitimately carry local edits - a hand-tuned Caddyfile.local, a cherry-picked
  # fix - and an installer that throws them away to get a clean fast-forward is an
  # installer that causes outages. Dirty means "leave it and say so".
  if [ -n "$(git -C "$DIR" status --porcelain 2>/dev/null || true)" ]; then
    warn "${DIR} has uncommitted changes, so it was left exactly as it is - nothing was fetched or merged. Review them ('git -C ${DIR} status'), then update it yourself with 'git -C ${DIR} pull --ff-only'."
  else
    BRANCH="$(git -C "$DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo HEAD)"
    if [ "$BRANCH" = "main" ]; then
      log "fetching and fast-forwarding ${DIR} (main)"
      # --force on tags for the same reason bootstrap.sh uses it: an upstream
      # history rewrite re-points a tag, and without --force this checkout keeps
      # the stale object forever and deploys a release nobody published.
      git -C "$DIR" fetch --tags --force --prune origin
      git -C "$DIR" merge --ff-only origin/main
    else
      warn "${DIR} is on branch '${BRANCH}', not main, so it was not updated. That is usually deliberate; if it is not, 'git -C ${DIR} checkout main' and re-run."
    fi
  fi
else
  log "cloning ${OWNER}/vidra into ${DIR}"
  # Created as root (it is under /opt) but OWNED by whoever is running this, so
  # every git and bootstrap command below - and every one the operator types next
  # - works without sudo. deploy/provision.sh later chowns the whole directory to
  # the 'vidra' service user, which is what the backup timer runs as.
  as_root install -d -m 0755 -o "$(id -un)" -g "$(id -gn)" "$DIR"
  git clone "https://github.com/${OWNER}/vidra.git" "$DIR"
fi

log "bootstrapping the component checkouts at ${TAG}"
# bootstrap.sh is the ONE copy of "which repos, cloned how". It is idempotent, it
# honours VIDRA_REF by detaching each checkout at that tag, and meta-ci exercises
# its update path on every run - three reasons not to re-implement three git
# clones here.
( cd "$DIR" && VIDRA_REF="$TAG" VIDRA_GH_OWNER="$OWNER" ./bootstrap.sh ) \
  || die "bootstrap.sh failed. The meta-repo is cloned at ${DIR}; fix the cause (usually a tag that does not exist in every component repo) and re-run this installer, or just './bootstrap.sh' from ${DIR}."

# --- 6/7 the vidra CLI -------------------------------------------------------------
step "6/7 the vidra CLI"
command -v sha256sum >/dev/null 2>&1 \
  || die "no sha256sum on this host (coreutils), so a downloaded binary cannot be verified - and an unverified binary that is about to hold your instance's secrets is not worth installing. 'apt-get install coreutils' and re-run."

ASSET="vidra_${TAG}_linux_${ARCH}"
BASE_URL="https://github.com/${OWNER}/vidra-core/releases/download/${TAG}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM

# Returns 0 on 200, 44 on 404 (which for these two URLs means "this release has no
# assets", a case with its own explanation below), 1 on anything else. curl writes
# the error body to the output file, so a failed download is deleted rather than
# left to look like a binary.
LAST_HTTP_CODE=""
http_get() {
  # curl prints the code through -w even when the transfer failed - "000" when
  # there was no HTTP response at all - so what has to be discarded here is its
  # EXIT STATUS, not its output. The obvious `|| echo 000` appends a second code
  # to the first and reports "HTTP 000000", which is not a number anyone can look
  # up; `|| true` after the assignment keeps `set -e` happy without inventing one.
  LAST_HTTP_CODE="$(curl -sSL -o "$2" -w '%{http_code}' "$1" 2>/dev/null)" || true
  case "$LAST_HTTP_CODE" in
    200) return 0 ;;
    404) rm -f "$2"; return 44 ;;
    *)   rm -f "$2"; return 1 ;;
  esac
}

# What to put in a failure message. A bare code is the right answer when there IS
# one; "000" means the request never got an HTTP response at all, and printing it
# as a status sends an operator looking up a code that does not exist instead of
# checking the thing that is actually broken.
http_why() {
  case "$LAST_HTTP_CODE" in
    000|"") printf 'the transfer never completed - DNS, connectivity, a proxy or TLS' ;;
    *)      printf 'HTTP %s' "$LAST_HTTP_CODE" ;;
  esac
}

no_assets() {
  cat >&2 <<EOF

[install] ERROR: release ${TAG} of ${OWNER}/vidra-core carries no ${ASSET}.

  Releases only carry CLI binaries from the one cut after vidra-core's
  release-assets workflow landed; v0.2.0 and everything before it predate it and
  never will. Building one now would mean building a tag whose source predates
  the build claiming to be it.

  Two ways forward:

    * Pick a newer release:  --ref <tag>
      https://github.com/${OWNER}/vidra-core/releases

    * Build it from the checkout this installer has already made:
          cd ${DIR}/vidra-core && make build-vidra
          sudo install -m 0755 bin/vidra /usr/local/bin/vidra
      then finish the install by hand:
          cd ${DIR} && vidra setup --template env/production.env.example

  Nothing was rolled back. ${DIR} is a complete deployment tree pinned at ${TAG};
  re-running this installer picks up from here.

EOF
  exit 1
}

log "downloading ${ASSET}"
if ! http_get "${BASE_URL}/${ASSET}" "${WORK}/${ASSET}"; then
  [ "$LAST_HTTP_CODE" != "404" ] || no_assets
  die "downloading ${BASE_URL}/${ASSET} failed ($(http_why)). ${DIR} is intact - re-run when the network is."
fi
if ! http_get "${BASE_URL}/SHA256SUMS" "${WORK}/SHA256SUMS"; then
  [ "$LAST_HTTP_CODE" != "404" ] || no_assets
  die "downloading ${BASE_URL}/SHA256SUMS failed ($(http_why)). The binary is NOT installed unverified - re-run when the network is."
fi

# One line, matched on the exact file NAME rather than by a regex over the whole
# file: the two architectures' names differ by three characters and an unanchored
# match is how the wrong checksum gets checked against the right file.
awk -v want="$ASSET" '$2 == want || $2 == "*" want { print; found = 1 }
                      END { exit !found }' \
  "${WORK}/SHA256SUMS" > "${WORK}/SHA256SUMS.one" \
  || die "SHA256SUMS from release ${TAG} lists no entry for ${ASSET}, so the download cannot be verified. Not installing it."

if ( cd "$WORK" && sha256sum -c SHA256SUMS.one >/dev/null 2>&1 ); then
  log "checksum verified"
else
  rm -f "${WORK}/${ASSET}"
  die "CHECKSUM MISMATCH on ${ASSET} from release ${TAG}. The download has been deleted and nothing was installed. This is either a corrupted transfer or a tampered asset; re-run, and if it happens again do not work around it."
fi

if [ -x /usr/local/bin/vidra ] && cmp -s "${WORK}/${ASSET}" /usr/local/bin/vidra; then
  log "/usr/local/bin/vidra is already byte-for-byte this binary - leaving it alone"
else
  as_root install -m 0755 "${WORK}/${ASSET}" /usr/local/bin/vidra
  log "installed /usr/local/bin/vidra (${TAG})"
fi
VIDRA_BIN=/usr/local/bin/vidra

# --- 7/7 setup ---------------------------------------------------------------------
step "7/7 setup"
ENV_FILE="${DIR}/env/production.env"

# The runbook's proof, at the moment it matters: BEFORE anything writes secrets
# into that path. `git check-ignore` answers about a path, not about a file, so it
# works before the file exists - which is the only useful time to ask.
log "env/production.env is git-ignored, by this rule:"
( cd "$DIR" && git check-ignore -v env/production.env ) \
  || die "env/production.env is NOT git-ignored in ${DIR}. Stop: the next command writes every secret this instance has into that file. Fix .gitignore first."

if [ -f "$ENV_FILE" ]; then
  # The whole reason this installer is safe to re-run. That file holds the KEKs
  # that seal MFA/federation/ATProto material in the database; regenerating them
  # orphans everything already sealed under the old ones. `vidra setup` refuses to
  # rewrite an existing env file without --yes, and this script does not pass
  # --yes - not as a default, not ever.
  log "${ENV_FILE} already exists - leaving it EXACTLY as it is, and not running the interview."
  cat <<EOF

  Nothing was regenerated: that file holds the KEKs sealing data already in the
  database, and re-minting them orphans it. To change answers deliberately:

      cd ${DIR} && vidra setup --template env/production.env.example --yes
      cd ${DIR} && vidra setup --check env/production.env      # just validate it

  'vidra setup --yes' still preserves every value the file already sets; only
  '--rotate <VAR>' replaces a secret, and a *_KEK additionally needs
  --yes-i-know.

EOF
elif have_tty; then
  log "running the setup interview (vidra setup --template env/production.env.example)"
  echo
  # </dev/tty is the entire trick of a `curl ... | sh` install: stdout and stderr
  # are already the terminal, but stdin is the script being piped in, and the
  # wizard refuses a non-terminal stdin by design rather than asking eleven
  # questions that all read EOF (vidra-core/cmd/vidra/setup.go).
  if ( cd "$DIR" && "$VIDRA_BIN" setup --template env/production.env.example < /dev/tty ); then
    SETUP_RAN=1
  else
    die "'vidra setup' exited non-zero. Nothing else was changed and ${DIR} is a complete deployment tree - re-run just the interview: 'cd ${DIR} && vidra setup --template env/production.env.example'."
  fi
else
  SETUP_RAN=0
  cat <<EOF

[install] The deployment tree and the CLI are installed, but the setup interview
needs a terminal and there is none here (no /dev/tty). It is not skipped - it is
yours to run, either way:

  On a terminal:
      cd ${DIR} && vidra setup --template env/production.env.example

  Unattended, with the answers as flags:
      cd ${DIR} && vidra setup --template env/production.env.example \\
          --non-interactive \\
          --domain video.example.org --instance-name "Example Video" \\
          --registration closed --tls-mode acme --acme-email you@example.org \\
          --storage local

  Or from an answers file ("flag-name = value" lines, no dashes):
      cd ${DIR} && vidra setup --template env/production.env.example \\
          --non-interactive --answers answers.txt

  'vidra setup -h' lists every flag, including the @file / \$VIDRA_SETUP_*
  indirections that keep secrets out of argv (and out of your shell history).

EOF
  exit 0
fi

# --- what happens next --------------------------------------------------------------
# Deliberately NOT a second copy of what 'vidra setup' just printed. It ends with
# the render check and the owner-claim sequence - the api mints a one-time token
# at boot and prints it to its own log - and two versions of that instruction is
# one version too many. This says what surrounds it.
step "done"
if [ "${SETUP_RAN:-0}" -eq 1 ]; then
  cat <<EOF
Do the two steps 'vidra setup' printed above (the compose render check, then the
owner claim once the stack is up - every signup path answers 403 until it is
redeemed). Around them:

EOF
fi
cat <<EOF
  Prepare the host, before the first deploy:

      cd ${DIR} && sudo ./deploy/provision.sh

  Swap, the 'vidra' service user, ${DIR}'s ownership, the docker log cap,
  unattended-upgrades and the nightly backup timer - installed AND verified. It
  opens no port and never touches sshd; it prints the exact list your CLOUD
  firewall must allow (a host ufw does not filter Docker-published ports).

  Deploy:

      cd ${DIR} && vidra deploy

  That execs deploy/deploy.sh unchanged: pre-deploy dump, pull, the core and
  search migrations as two separate exit-code-gated steps, 'up -d --no-build',
  then /readyz, frontend and TLS-edge probes. Edit the VIDRA_*_TAG values in
  env/production.env first if you want something other than ${TAG}.

  Reach it from your workstation, before DNS and TLS exist:

      ssh -L 8080:localhost:8080 <user>@<this host>    # then http://localhost:8080/readyz
      ssh -L 3000:localhost:3000 <user>@<this host>    # the frontend

  The production overlay publishes the api and the frontend on 127.0.0.1 only and
  Postgres, Redis and search on nothing at all - an SSH tunnel is the intended way
  in, not a workaround.

  Then:

      cd ${DIR} && vidra doctor     # 18 checks: compose, exposure, config, backups, reachability
      cd ${DIR} && vidra status     # what is running, and whether it answers

  deploy/README.md is the manual path for every one of these, and the source of
  truth for all of them.

EOF

if [ -n "$WARNINGS" ]; then
  printf '[install] thing(s) that need you:\n%s\n' "$WARNINGS"
fi

log "done."
