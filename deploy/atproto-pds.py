"""Prepare the local Personal Data Server without replacing account signing secrets."""
import argparse
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
from urllib.parse import urlsplit


def hostname(site):
    origin = urlsplit(site)
    host = origin.hostname or ""
    if origin.scheme != "https" or origin.username is not None or origin.password is not None:
        raise ValueError("local PDS requires an HTTPS PUBLIC_BASE_URL")
    labels = host.split(".")
    if (len(host) > 249 or len(labels) < 2 or labels[-1].isdigit() or
            any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)):
        raise ValueError("local PDS requires a public DNS hostname in PUBLIC_BASE_URL")
    return "pds." + host


def rotation_key():
    # The PDS consumes the raw secp256k1 scalar. Let OpenSSL generate a
    # valid key on this curve and extract only its private component.
    pem = subprocess.run(["openssl", "ecparam", "-name", "secp256k1", "-genkey", "-noout"],
                         check=True, capture_output=True).stdout
    key = subprocess.run(["openssl", "ec", "-noout", "-text"], input=pem,
                         check=True, capture_output=True).stdout.decode("ascii")
    scalar = re.search(r"(?ms)^priv:\s*([0-9a-f:\s]+?)^pub:", key)
    if scalar is None:
        raise ValueError("OpenSSL returned an unrecognized PDS rotation key")
    scalar = re.sub(r"[:\s]", "", scalar[1])
    # LibreSSL may print a leading ASN.1 sign byte. The PDS uses 32 bytes.
    if len(scalar) == 66 and scalar.startswith("00"):
        scalar = scalar[2:]
    if len(scalar) != 64:
        raise ValueError("OpenSSL returned an invalid PDS rotation key length")
    return scalar


# SEC 2, section 2.4.1: group order for the PDS secp256k1 rotation key.
SECP256K1_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
ROTATION_KEY = "PDS_PLC_ROTATION_KEY_K256_PRIVATE_KEY_HEX"


def random_secret():
    return secrets.token_hex(32)


SECRET_GENERATORS = {
    "PDS_JWT_SECRET": random_secret,
    "PDS_ADMIN_PASSWORD": random_secret,
    ROTATION_KEY: rotation_key,
}


def prepare(path, data_dir):
    if path.is_symlink() or data_dir.is_symlink():
        raise ValueError("PDS data and secrets must use their original paths")
    data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if data_dir.stat().st_mode & 0o077:
        raise ValueError("PDS data directory must be private (mode 0700)")
    if path.exists():
        validate(path)
        return
    if any(data_dir.iterdir()):
        raise ValueError("PDS data already exists; restore its original secret file")
    values = {"PDS_BLOBSTORE_DISK_LOCATION": "/pds/blocks"}
    values.update((key, generate()) for key, generate in SECRET_GENERATORS.items())
    # Publish an already-complete 0600 file. Concurrent deploys can never
    # overwrite a winner's PLC rotation key or observe a partial first write.
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".atproto-pds-") as temp:
        for key, value in values.items():
            temp.write(f"{key}={value}\n")
        temp.flush()
        os.fsync(temp.fileno())
        try:
            os.link(temp.name, path)
        except FileExistsError:
            pass
    validate(path)


def validate(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError("PDS secrets must be a private regular file (mode 0600)")
    entries = dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)
    for key in SECRET_GENERATORS:
        if not entries.get(key):
            raise ValueError(f"PDS secrets file lacks {key}; restore the original credentials")
    scalar = entries[ROTATION_KEY]
    if not re.fullmatch(r"[0-9a-fA-F]{64}", scalar) or not 0 < int(scalar, 16) < SECP256K1_ORDER:
        raise ValueError("invalid PDS rotation key; restore the original credentials")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--hostname", metavar="PUBLIC_BASE_URL")
    mode.add_argument("--prepare", type=Path, metavar="SECRET_FILE")
    parser.add_argument("--data-dir", type=Path, default=Path("data/atproto-pds"))
    args = parser.parse_args()
    try:
        if args.hostname is not None:
            print(hostname(args.hostname))
        else:
            prepare(args.prepare, args.data_dir)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"atproto-pds: {exc}\n")
