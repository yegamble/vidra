#!/usr/bin/env python3
"""Provision only the eligibility reader using the known local Compose database."""
import argparse
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import tempfile

ROLE = "vidra_native_reference_reader"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, required=True)
    parser.add_argument("--uid", type=int, required=True)
    parser.add_argument("--gid", type=int, required=True)
    parser.add_argument("--container", default="vidra-postgres-1")
    parser.add_argument("--project", default="vidra")
    args = parser.parse_args()
    st = args.dir.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid() or st.st_mode & 0o022:
        sys.exit("Expected a trusted root-controlled credential directory")
    labels = json.loads(subprocess.check_output(["docker", "inspect", "--format", "{{json .Config.Labels}}", args.container], text=True))
    if labels.get("com.docker.compose.project") != args.project or labels.get("com.docker.compose.service") != "postgres":
        sys.exit("Unexpected database container")
    cli = ["docker", "exec", "-i", args.container, "sh", "-ec",
           'test "$POSTGRES_DB" = vidra && exec psql -XAtq --no-password -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d vidra']
    def sql(statement):
        result = subprocess.run(cli, input=statement, text=True, capture_output=True)
        if result.returncode:
            # The SQL can contain a SCRAM verifier. Never print verbose SQL errors.
            sys.exit("Native reader database check failed")
        return result.stdout.strip()
    if sql("SELECT to_regclass('public.ipfs_public_reference_videos') IS NOT NULL;") != "t":
        sys.exit("Release eligibility view absent")
    pgpass = args.dir / "pgpass"
    prefix = f"postgres:5432:vidra:{ROLE}:"
    exists = sql(f"SELECT EXISTS(SELECT FROM pg_roles WHERE rolname='{ROLE}');") == "t"
    if not pgpass.exists():
        if exists or pgpass.is_symlink():
            sys.exit("Existing role or symlink without escrowable local password")
        # The link is exclusive. Exceptional exits can be retried using the same saved key.
        with tempfile.NamedTemporaryFile(dir=args.dir, mode="w") as tmp:
            tmp.write(prefix + secrets.token_hex(32) + "\n")
            tmp.flush()
            os.fchown(tmp.fileno(), args.uid, args.gid)
            os.fchmod(tmp.fileno(), 0o400)
            os.fsync(tmp.fileno())
            os.link(tmp.name, pgpass)
    ps = pgpass.lstat()
    if not stat.S_ISREG(ps.st_mode) or ps.st_uid != args.uid or ps.st_gid != args.gid or ps.st_mode & 0o377:
        sys.exit("Unexpected credential ownership or mode")
    match = re.fullmatch(re.escape(prefix) + r"([a-f0-9]{64})\n", pgpass.read_text())
    if not match:
        sys.exit("Unexpected credential format")
    password = match[1].encode()
    encode = lambda b: base64.b64encode(b).decode()
    def verifier(salt, iterations):
        salted = hashlib.pbkdf2_hmac("sha256", password, salt, iterations)
        client = hmac.digest(salted, b"Client Key", "sha256")
        server = hmac.digest(salted, b"Server Key", "sha256")
        return f"SCRAM-SHA-256${iterations}:{encode(salt)}${encode(hashlib.sha256(client).digest())}:{encode(server)}"
    if exists:
        actual = sql(f"SELECT rolpassword FROM pg_authid WHERE rolname='{ROLE}';")
        recipe = re.fullmatch(r"SCRAM-SHA-256\$(\d{1,7}):([+/=a-zA-Z0-9]+)\$[+/=a-zA-Z0-9]+:[+/=a-zA-Z0-9]+", actual)
        if not recipe or not hmac.compare_digest(verifier(base64.b64decode(recipe[2]), int(recipe[1])), actual):
            sys.exit("Existing role does not match the independently held credential")
        if sql(f"SELECT rolcanlogin AND NOT (rolsuper OR rolcreatedb OR rolcreaterole OR rolinherit OR rolreplication OR rolbypassrls) AND NOT EXISTS (SELECT FROM pg_auth_members WHERE member=r.oid) FROM pg_roles r WHERE rolname='{ROLE}';") != "t":
            sys.exit("Unexpected pre-existing role attributes")
        create = ""
    else:
        create = f"CREATE ROLE {ROLE} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 8 PASSWORD '{verifier(secrets.token_bytes(16), 8192)}';"
    # Unexpected effective application privileges abort the entire transaction.
    # PUBLIC's database TEMP and ordinary built-in functions are unaffected.
    result = sql(f"""BEGIN;
{create}
ALTER ROLE {ROLE} IN DATABASE vidra SET default_transaction_read_only=on;
ALTER ROLE {ROLE} IN DATABASE vidra SET statement_timeout='2s';
GRANT CONNECT ON DATABASE vidra TO {ROLE};
GRANT USAGE ON SCHEMA public TO {ROLE};
GRANT SELECT ON public.ipfs_public_reference_videos TO {ROLE};
DO $grant_check$
BEGIN
  IF EXISTS (SELECT FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f')
          AND (has_table_privilege('{ROLE}',c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
            OR (c.oid <> 'public.ipfs_public_reference_videos'::regclass
                AND has_any_column_privilege('{ROLE}',c.oid,'SELECT,INSERT,UPDATE,REFERENCES'))))
    OR EXISTS (SELECT FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND CASE WHEN c.relkind='S' THEN has_sequence_privilege('{ROLE}',c.oid,'SELECT,USAGE,UPDATE') ELSE false END)
    OR EXISTS (SELECT FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='public' AND p.prosecdef AND has_function_privilege('{ROLE}',p.oid,'EXECUTE'))
    OR has_database_privilege('{ROLE}',current_database(),'CREATE')
    OR has_schema_privilege('{ROLE}','public','CREATE') THEN
    RAISE EXCEPTION 'Unexpected app privileges';
  END IF;
END
$grant_check$;
COMMIT;
SELECT 'verified';""")
    if result != "verified":
        sys.exit("Reader verification failed")
    print("Native eligibility reader verified")


if __name__ == "__main__":
    main()
