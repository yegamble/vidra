"""Exercise the actual rollback query and the gate on both sides of the pull."""
import os
import re
import sqlite3
import subprocess
import unittest
from pathlib import Path

from rollback_floor_test import extract


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "deploy/rollback.sh").read_text()
QUIET = extract("rollback.sh", "processed_uploads_quiet")
GATE = extract("rollback.sh", "processed_uploads_gate")


class ReconstructedUploadsRollback(unittest.TestCase):
    def test_guard_selects_only_work_that_needs_scan_aware_core(self):
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.executescript("""
            CREATE TABLE upload_sessions(purpose text, state text, expires_at text);
            CREATE TABLE video_files(video_id text, kind text, storage_key text);
            CREATE TABLE transcode_jobs(video_id text, state text, source_key text);
        """)
        query = re.search(r'local sql="(.*?)"', QUIET, re.S).group(1)
        files = "web-videos/v.vidra-processed.mp4"
        cases = {
            "upload_sessions": [
                (("processed", "active", "2999"), True),
                (("processed", "active", "2000"), False),
                (("processed", "processing", "2000"), True),
                (("processed", "queued", "2000"), True),
                (("processed", "cancelled", "2999"), False),
                (("processed", "completed", "2999"), False),
                (("upload", "queued", "2999"), False),
                (("replace", "processing", "2999"), False),
            ],
            "video_files": [
                (("v", "original", files), True),
                (("other", "original", files), False),
                (("v", "original", "web-videos/v.mp4"), False),
                (("v", "rendition", files), False),
            ],
            "transcode_jobs": [
                (("v", "pending", files), True), (("v", "running", files), True),
                (("v", "failed", files), True), (("v", "done", files), False),
                (("v", "pending", "web-videos/v.mp4"), False),
            ],
        }
        for table, rows in cases.items():
            for row, expected in rows:
                with self.subTest(table=table, row=row):
                    db.execute(f"INSERT INTO {table} VALUES (?, ?, ?)", row)
                    self.assertEqual(bool(db.execute(query).fetchone()[0]), expected)
                    db.execute(f"DELETE FROM {table}")

    def exercise(self, **env):
        setup = """
set -euo pipefail
PROCESSED_UPLOADS_RECHECK=0
REPO_ROOT=.
COMPOSE=(compose)
log() { echo "$*"; }
die() { echo "$*" >&2; exit 1; }
env_get() { case "$1" in VIDRA_CORE_TAG) echo current;; UPLOAD_NORMALIZER_DIR) echo "$DIR";; esac; }
is_bundle_tree() { return 1; }
python3() { case "$*" in *'--core current '*) return "$CURRENT";; *) return "$TARGET";; esac; }
compose() { echo api1; echo api2; }
docker() { echo "checked runtime $2"; [ "$2" != "$ENABLED_REPLICA" ]; }
privacy_pg() {
  [ "$1" = '-c default_transaction_read_only=on' ] || exit 9
  case "$2" in *pg_constraint*) PG_OUT="$SCHEMA";; *) PG_OUT="$ROWS";; esac
  PRIVACY_UNASKED="database unavailable"
  [ "$PG_OUT" != error ]
}
"""
        run = subprocess.run(["bash", "-c", setup + QUIET + GATE +
                              '\nprocessed_uploads_gate\necho "recheck=$PROCESSED_UPLOADS_RECHECK"\n'],
                             capture_output=True, text=True, env={**os.environ,
                             "CORE_TAG": "target", "CURRENT": "0", "TARGET": "4",
                             "DIR": "", "SCHEMA": "t", "ROWS": "f", "ENABLED_REPLICA": "", **env})
        return run.returncode, run.stdout + run.stderr

    def test_fresh_admission_stored_sources_or_unknown_state_refuse(self):
        for env in ({"ENABLED_REPLICA": "api2"}, {"ROWS": "t"}, {"ROWS": "error"},
                    {"SCHEMA": "error"}, {"ROWS": "unexpected"}):
            with self.subTest(env=env):
                code, out = self.exercise(**env)
                self.assertNotEqual(code, 0, out)
                self.assertNotIn("recheck=", out)

    def test_old_install_compatible_target_and_component_only_skip(self):
        for env in ({"CURRENT": "4"}, {"TARGET": "0"}, {"CORE_TAG": ""}, {"SCHEMA": "f"}):
            with self.subTest(env=env):
                code, out = self.exercise(ROWS="t", **env)
                self.assertEqual(code, 0, out)
                self.assertIn("recheck=0", out)
                self.assertNotIn("checked runtime", out)

    def test_closed_admission_and_no_rows_rechecked_before_restart(self):
        code, out = self.exercise()
        self.assertEqual(code, 0, out)
        self.assertIn("checked runtime api1", out)
        self.assertIn("checked runtime api2", out)
        self.assertIn("recheck=1", out)
        gate = SCRIPT.index("\nprocessed_uploads_gate\n")
        self.assertLess(gate, SCRIPT.index('ENV_SNAPSHOT='))
        recheck = SCRIPT.index('processed_uploads_quiet || restore_env_and_die')
        self.assertLess(SCRIPT.index('"${COMPOSE[@]}" pull'), recheck)
        self.assertLess(recheck, SCRIPT.index('"${COMPOSE[@]}" up -d --no-build'))
