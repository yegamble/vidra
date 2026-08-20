#!/usr/bin/env bash
#
# Prepare a fresh Ubuntu/Debian host to run Vidra: swap, the service user and
# /opt/vidra, the Docker log cap, unattended security upgrades, and the nightly
# backup timer — the "Host prerequisites" section of deploy/README.md, executed.
#
#   sudo ./deploy/provision.sh          # asks once, then applies
#   sudo ./deploy/provision.sh --yes    # no prompt (cloud-init, CI, re-runs)
#
# Run it as root, BEFORE or AFTER the first deploy — it is idempotent, so a
# re-run after adding a compose profile is the supported way to re-read the
# firewall requirements.
#
# WHAT IT DOES NOT DO, deliberately:
#   * install Docker or Compose. That is the installer's job (and a
#     hand-rolled `apt-get install docker.io` gets you a version below the 2.24
#     Compose floor the prod overlay needs). This script configures the daemon
#     it expects to find and says so when it is missing.
#   * touch sshd, or open a single port. Both are checked and REPORTED. Editing
#     sshd_config over the SSH session you are editing it from is how hosts are
#     lost, and a host firewall does not filter Docker-published ports anyway
#     (see the DOCKER-USER note it prints) — the real control is a cloud
#     firewall outside the box, which this script cannot reach.
#   * overwrite an /etc/docker/daemon.json that already says something else. It
#     prints the keys to merge and carries on: that file is where an operator
#     configures storage drivers, registry mirrors and DNS, and clobbering it to
#     add a log cap is a much bigger outage than uncapped logs.
#
# Environment overrides: VIDRA_DIR (default /opt/vidra), VIDRA_USER (default
# vidra), VIDRA_SWAP_SIZE (default 4G), ENV_FILE (default <dir>/env/production.env,
# read ONLY to work out which ports the enabled compose profiles need).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VIDRA_DIR="${VIDRA_DIR:-/opt/vidra}"
VIDRA_USER="${VIDRA_USER:-vidra}"
SWAP_SIZE="${VIDRA_SWAP_SIZE:-4G}"
SWAPFILE="${VIDRA_SWAPFILE:-/swapfile}"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/env/production.env}"
DAEMON_JSON="/etc/docker/daemon.json"
DAEMON_JSON_WANT='{"log-driver":"json-file","log-opts":{"max-size":"10m","max-file":"5"}}'

log()  { printf '[provision] %s\n' "$*"; }
die()  { printf '[provision] ERROR: %s\n' "$*" >&2; exit 1; }
step() { printf '\n[provision] ===== %s =====\n' "$*"; }

# Warnings are collected and reprinted at the end. A provisioning run scrolls
# several screens, and the three things this script refuses to change for you are
# exactly the three an operator must not miss.
WARNINGS=()
warn() {
  printf '[provision] WARNING: %s\n' "$*" >&2
  WARNINGS+=("$*")
}

ASSUME_YES=0
while [ $# -gt 0 ]; do
  case "$1" in
    -y|--yes)  ASSUME_YES=1; shift ;;
    -h|--help) sed -n '2,31p' "$0"; exit 0 ;;
    *) die "unknown argument: $1 (only --yes and --help are accepted)" ;;
  esac
done

# --- platform ------------------------------------------------------------------
# Everything below is apt, adduser, systemd and /proc. On anything else the
# individual commands would fail one at a time, half-applied, which is worse than
# not starting: point at the runbook and stop.
[ "$(uname -s)" = "Linux" ] \
  || die "this script provisions a Linux host (found $(uname -s)). Follow 'Host prerequisites' in deploy/README.md by hand."
command -v apt-get >/dev/null 2>&1 \
  || die "no apt-get found — this recipe targets Ubuntu/Debian. Every step has a manual equivalent in 'Host prerequisites' in deploy/README.md; translate them to your package manager and run deploy/provision.sh's systemd section by hand."
[ "$(id -u)" -eq 0 ] \
  || die "run as root (sudo ./deploy/provision.sh): this creates a user, writes /etc/docker/daemon.json and installs systemd units."

# Validated here rather than at first use: the dd fallback below converts this to
# a count of 1 MiB blocks, and '512M' would reach that arithmetic as a syntax
# error halfway through creating a swapfile.
printf '%s' "$SWAP_SIZE" | grep -qE '^[0-9]+[Gg]$' \
  || die "VIDRA_SWAP_SIZE must be a whole number of gigabytes, e.g. '4G' — got '${SWAP_SIZE}'"

# --- what the firewall will have to allow --------------------------------------
# Worked out BEFORE the confirmation so the prompt can state it: an operator who
# says yes should already know that answering "media" to `vidra setup` means
# opening 1935 to the world.
#
# The env file is read through deploy/lib.sh's env_get — the same reader every
# deploy script uses, and specifically NOT `source`, because that file is
# operator-edited and full of secrets. A host being provisioned for the first
# time has no env file yet; the defaults are then what an unedited
# env/production.env.example selects.
PROFILES="core frontend"
if [ -f "$ENV_FILE" ]; then
  # shellcheck source=deploy/lib.sh
  . "$REPO_ROOT/deploy/lib.sh"
  PROFILES="$(env_get VIDRA_COMPOSE_PROFILES "core frontend") $(env_get EXTRA_COMPOSE_PROFILES "")"
  log "read compose profiles from ${ENV_FILE}: ${PROFILES}"
else
  log "no env file at ${ENV_FILE} yet — assuming the default profiles (${PROFILES}) for the firewall summary"
fi

PORTS="22/tcp (admin IP only)  80/tcp  443/tcp"
case " $PROFILES " in
  *" media "*) PORTS="$PORTS  1935/tcp (RTMP ingest)" ;;
esac
case " $PROFILES " in
  *" ipfs "*)  PORTS="$PORTS  4001/tcp+udp (IPFS swarm)" ;;
esac

# --- confirmation --------------------------------------------------------------
# Same shape as deploy/release.sh: --yes for the scripted caller, a prompt for a
# human, and a refusal when there is neither. A provisioning script that silently
# proceeds under cron or a stray pipe is one that reformats swap on a host
# somebody meant to leave alone.
if [ "$ASSUME_YES" = "1" ]; then
  log "--yes given — not prompting."
elif [ -t 0 ]; then
  cat <<EOF

About to provision this host for Vidra:
  service user     ${VIDRA_USER}   (in the docker group — that is root-equivalent)
  directory        ${VIDRA_DIR}
  swap             ${SWAP_SIZE} at ${SWAPFILE} (+ an /etc/fstab line)
  docker daemon    log cap in ${DAEMON_JSON} (never overwritten if it differs)
  apt              unattended-upgrades, enabled
  systemd          vidra-backup.service + .timer, enabled and verified
Your firewall must then allow: ${PORTS}

EOF
  read -r -p 'Type "provision" to continue: ' answer
  [ "$answer" = "provision" ] || { echo "Aborted."; exit 1; }
else
  die "refusing to provision a host without confirmation and without a terminal. Re-run interactively, or pass --yes (which is what deploy/cloud-init.yaml.example does)."
fi

# --- 1/6 swap ------------------------------------------------------------------
# The difference between a slow transcode and an OOM-killed Postgres. ffmpeg runs
# inside the api container and a TargetAll job is twelve full encode passes.
step "1/6 swap"
if [ "$(awk 'NR > 1' /proc/swaps | wc -l)" -gt 0 ]; then
  log "swap is already active, leaving it alone:"
  awk 'NR > 1 { print "  " $0 }' /proc/swaps
elif [ -e "$SWAPFILE" ]; then
  warn "${SWAPFILE} exists but no swap is active — it was created and never swapon'd, or it is something else entirely. Not touching it; run 'swapon ${SWAPFILE}' by hand once you know what it is."
else
  log "creating ${SWAP_SIZE} of swap at ${SWAPFILE}"
  # fallocate is instant but fails on filesystems without extent preallocation
  # (btrfs, zfs, some overlay setups) — and a swapfile with holes is refused by
  # mkswap, so falling back to a real write is not optional.
  if ! fallocate -l "$SWAP_SIZE" "$SWAPFILE" 2>/dev/null; then
    log "fallocate unavailable on this filesystem, writing ${SWAPFILE} with dd (slower)"
    dd if=/dev/zero of="$SWAPFILE" bs=1M count="$(( ${SWAP_SIZE%[Gg]} * 1024 ))" status=none
  fi
  chmod 600 "$SWAPFILE"
  # A failure here is a WARNING, not a death: some roots genuinely cannot host a
  # swapfile (ZFS, an unprivileged container, overlayfs), and swap is a
  # performance cushion while the backup timer two steps down is data safety.
  # Dying here would skip the timer, which is the wrong thing to lose.
  #
  # The half-made file is REMOVED on failure so the /etc/fstab check below sees
  # no swapfile and writes no line: an fstab entry for a file `swapon -a` cannot
  # activate turns every subsequent boot into a failed unit.
  if mkswap "$SWAPFILE" >/dev/null 2>&1 && swapon "$SWAPFILE" 2>/dev/null; then
    log "swap on"
  else
    rm -f "$SWAPFILE"
    warn "could not activate swap at ${SWAPFILE} on this filesystem (mkswap or swapon refused it) — the file has been removed and /etc/fstab left alone. Add swap another way before running a transcode: without it, ffmpeg's peak makes the OOM killer choose between Postgres and the api."
  fi
fi
# The fstab line is checked separately: swap can be active from a manual swapon
# and still not survive a reboot, which is the failure this exists to prevent and
# the one nobody notices until the reboot.
#
# Guarded on ${SWAPFILE} being ACTIVE RIGHT NOW, not merely existing. Only what
# demonstrably works gets persisted. A host that swaps to a partition has no
# ${SWAPFILE} at all; a host with a leftover ${SWAPFILE} that mkswap never
# touched would, if we wrote the line anyway, fail `swapon -a` on every single
# boot for a file that is not a swap area.
if ! awk -v f="$SWAPFILE" 'NR > 1 && $1 == f { found = 1 } END { exit !found }' /proc/swaps; then
  log "${SWAPFILE} is not active swap on this host — leaving /etc/fstab alone"
elif grep -qsE "^[[:space:]]*${SWAPFILE}[[:space:]]" /etc/fstab; then
  log "/etc/fstab already mounts ${SWAPFILE} at boot"
else
  printf '%s none swap sw 0 0\n' "$SWAPFILE" >> /etc/fstab
  log "added ${SWAPFILE} to /etc/fstab"
fi

# --- 2/6 service user + directory ----------------------------------------------
step "2/6 service user and ${VIDRA_DIR}"
if id -u "$VIDRA_USER" >/dev/null 2>&1; then
  log "user ${VIDRA_USER} already exists"
elif command -v adduser >/dev/null 2>&1; then
  # --disabled-password, not --disabled-login: the account must be usable by
  # systemd and by `su - vidra`, it just must not have a password to guess.
  # --gecos "" because without it adduser asks five questions, and this script
  # has to work under cloud-init where nothing is there to answer them.
  adduser --disabled-password --gecos "" "$VIDRA_USER" >/dev/null
  log "created user ${VIDRA_USER}"
else
  # adduser is a Debian perl wrapper and minimal images ship without it.
  # useradd is in the base system everywhere; -m for the home directory, and no
  # password is set at all, which is the same locked account --disabled-password
  # produces.
  useradd -m -s /bin/bash "$VIDRA_USER"
  log "created user ${VIDRA_USER} (via useradd — adduser is not installed here)"
fi

if getent group docker >/dev/null 2>&1; then
  if id -nG "$VIDRA_USER" | tr ' ' '\n' | grep -qx docker; then
    log "${VIDRA_USER} is already in the docker group"
  else
    usermod -aG docker "$VIDRA_USER"
    log "added ${VIDRA_USER} to the docker group (this is root-equivalent on the host — inherent to Docker, not to this setup)"
  fi
else
  warn "there is no 'docker' group, so ${VIDRA_USER} could not be added to it — Docker is not installed yet. Install Docker Engine >= 24 and Compose >= 2.24, then re-run this script; until then the backup timer will fail at the daemon socket."
fi

mkdir -p "$VIDRA_DIR"
if [ "$(stat -c %U "$VIDRA_DIR")" = "$VIDRA_USER" ]; then
  log "${VIDRA_DIR} is already owned by ${VIDRA_USER}"
else
  chown -R "${VIDRA_USER}:${VIDRA_USER}" "$VIDRA_DIR" \
    || die "could not chown ${VIDRA_DIR} to ${VIDRA_USER} (read-only mount? immutable files?). This is fatal on purpose: the nightly backup runs AS ${VIDRA_USER} and writes ${VIDRA_DIR}/backups, so a partial chown becomes a timer that fails at 03:15 into a log nobody reads."
  log "chowned ${VIDRA_DIR} to ${VIDRA_USER}"
fi

# The shipped units hardcode User=vidra and WorkingDirectory=/opt/vidra. An
# override here is supported, but it makes those units wrong, and a backup timer
# that runs `cd /opt/vidra` on a host whose checkout is elsewhere fails every
# night into a log nobody reads.
if [ "$VIDRA_DIR" != "/opt/vidra" ] || [ "$VIDRA_USER" != "vidra" ]; then
  warn "VIDRA_DIR=${VIDRA_DIR} / VIDRA_USER=${VIDRA_USER} are not the defaults, but deploy/vidra-backup.service hardcodes User=vidra, Group=vidra and WorkingDirectory=/opt/vidra. Edit /etc/systemd/system/vidra-backup.service to match and 'systemctl daemon-reload', or the nightly backup fails silently."
fi

# --- 3/6 docker log cap --------------------------------------------------------
# The default json-file driver is UNBOUNDED, and the api writes a structured JSON
# line per request onto the same disk as Postgres and the media volume.
# docker-compose.prod.yml caps every service it defines; this is the backstop for
# anything started outside the compose stack.
step "3/6 docker daemon log cap"
mkdir -p "$(dirname "$DAEMON_JSON")"
if [ ! -e "$DAEMON_JSON" ]; then
  printf '%s\n' "$DAEMON_JSON_WANT" > "$DAEMON_JSON"
  log "wrote ${DAEMON_JSON}"
  if command -v docker >/dev/null 2>&1 && [ -n "$(docker ps -q 2>/dev/null || true)" ]; then
    # Restarting dockerd stops and restarts every container. On a host that is
    # already serving, that is an outage, and an uncapped log is not an
    # emergency — hand the decision to the operator.
    warn "${DAEMON_JSON} was written but the daemon has not read it: containers are running and 'systemctl restart docker' would bounce the site. Restart the daemon at the next maintenance window."
  elif command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet docker; then
    systemctl restart docker
    log "restarted docker (no containers were running)"
  else
    log "docker is not running yet; the cap applies when it starts"
  fi
elif [ "$(tr -d '[:space:]' < "$DAEMON_JSON")" = "$(printf '%s' "$DAEMON_JSON_WANT" | tr -d '[:space:]')" ]; then
  log "${DAEMON_JSON} already carries exactly this cap"
else
  warn "${DAEMON_JSON} exists and says something else — NOT overwriting it (it is also where storage drivers, registry mirrors and DNS live). Merge these keys into it by hand and restart docker: \"log-driver\": \"json-file\", \"log-opts\": {\"max-size\": \"10m\", \"max-file\": \"5\"}"
fi

# --- 4/6 unattended-upgrades ---------------------------------------------------
step "4/6 unattended security upgrades"
if dpkg-query -W -f='${Status}' unattended-upgrades 2>/dev/null | grep -q "ok installed"; then
  log "unattended-upgrades is already installed"
else
  log "installing unattended-upgrades"
  DEBIAN_FRONTEND=noninteractive apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq unattended-upgrades >/dev/null
fi
# 20auto-upgrades is what `dpkg-reconfigure -plow unattended-upgrades` writes.
# Written directly because dpkg-reconfigure is interactive-shaped and this script
# has to work under cloud-init, where there is no terminal to answer it.
AUTO_UPGRADES="/etc/apt/apt.conf.d/20auto-upgrades"
if grep -qs 'Unattended-Upgrade "1"' "$AUTO_UPGRADES"; then
  log "unattended upgrades are already enabled in ${AUTO_UPGRADES}"
else
  cat > "$AUTO_UPGRADES" <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
  log "enabled unattended upgrades in ${AUTO_UPGRADES}"
fi

# --- 5/6 the nightly backup timer ----------------------------------------------
# The units' own header documents these five commands. Doing them here is the
# point of the whole script: doctor reports a missing timer and a stale
# backups/last_success as failures, and both of those states start with an
# operator who read the runbook, nodded, and moved on.
step "5/6 nightly backup timer"
# `command -v systemctl` is not the test: the binary is present inside plenty of
# containers and WSL images where systemd is not PID 1, and there `daemon-reload`
# dies with "Failed to connect to bus" and takes the rest of this script with it.
# /run/systemd/system is the canonical "systemd is actually running here" probe,
# and it is what Debian's own maintainer scripts use.
if ! command -v systemctl >/dev/null 2>&1 || [ ! -d /run/systemd/system ]; then
  warn "systemd is not running here, so the backup timer was NOT installed. Schedule ${VIDRA_DIR}/deploy/backup.sh daily by whatever this system uses, and remember that 'vidra doctor' will report the timer as missing."
else
  install -m 0644 deploy/vidra-backup.service deploy/vidra-backup.timer /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable --now vidra-backup.timer
  # VERIFY, rather than trust the exit code above. `enable --now` on a timer
  # whose .service fails to parse can still report success, and the failure then
  # surfaces as "no backups have ever run", six weeks later, during a restore.
  systemctl is-enabled vidra-backup.timer >/dev/null \
    || die "vidra-backup.timer was installed but is not enabled — read 'systemctl status vidra-backup.timer'"
  systemctl is-active vidra-backup.timer >/dev/null \
    || die "vidra-backup.timer is enabled but not active — read 'systemctl status vidra-backup.timer'"
  log "vidra-backup.timer is enabled and active. Next run:"
  systemctl list-timers --no-pager vidra-backup.timer | sed 's/^/  /'
  log "prove the backup itself works before you rely on it: sudo systemctl start vidra-backup.service && journalctl -u vidra-backup.service -n 50"
fi

# --- 6/6 what this script refuses to change for you ----------------------------
step "6/6 checks (nothing below is modified)"

# `sshd -T` is the EFFECTIVE configuration — it resolves /etc/ssh/sshd_config.d
# drop-ins and Match blocks, which is why cloud images that set
# PasswordAuthentication in a drop-in read as "no" here and as "yes" to anyone
# grepping the main file.
if command -v sshd >/dev/null 2>&1; then
  SSHD_EFFECTIVE="$(sshd -T 2>/dev/null || true)"
  if [ -z "$SSHD_EFFECTIVE" ]; then
    warn "could not read the effective sshd config ('sshd -T' failed). Check PasswordAuthentication and PermitRootLogin by hand."
  else
    case "$SSHD_EFFECTIVE" in
      *"passwordauthentication yes"*)
        warn "sshd still accepts PASSWORDS. Set 'PasswordAuthentication no' in /etc/ssh/sshd_config (or a drop-in), 'systemctl restart ssh', and confirm you can still log in FROM A SECOND TERMINAL before closing this one." ;;
      *) log "OK: sshd refuses password authentication" ;;
    esac
    case "$SSHD_EFFECTIVE" in
      *"permitrootlogin yes"*)
        warn "sshd still permits ROOT login. Set 'PermitRootLogin no' (or 'prohibit-password' if your automation needs the key) and restart ssh." ;;
      *) log "OK: sshd does not permit password root login" ;;
    esac
  fi
else
  log "sshd is not installed here; nothing to check"
fi

cat <<EOF

[provision] FIREWALL — this script opens nothing, on purpose.
  Allow inbound:  ${PORTS}
  Deny everything else; leave outbound open.

  Use a CLOUD firewall (DigitalOcean Cloud Firewall or equivalent). It sits
  outside the droplet and is the only control Docker cannot bypass.

  A host 'ufw' does NOT filter Docker-published ports: Docker installs its own
  DOCKER-USER iptables chain and it is traversed BEFORE ufw's rules, so
  'ufw deny 5432' has no effect on a container publishing 5432. Run ufw as
  defence-in-depth for non-Docker services if you like, but do not believe it is
  protecting this stack.

  Verify from ANOTHER host once the stack is up — only the ports above may answer:
      nmap -Pn -p 22,80,443,1935,3000,4001,5432,6379,8080,8081 <this host>
EOF

if [ ${#WARNINGS[@]} -gt 0 ]; then
  printf '\n[provision] %d thing(s) need you:\n' "${#WARNINGS[@]}"
  for w in "${WARNINGS[@]}"; do
    printf '  * %s\n' "$w"
  done
  printf '\n'
fi

log "host provisioned. Next: install Vidra into ${VIDRA_DIR} (see deploy/README.md 'First bring-up'), then 'vidra setup'."
