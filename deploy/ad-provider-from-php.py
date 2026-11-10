#!/usr/bin/env python3
"""Turn an ad network's anti-adblock PHP file into the AD_ANTIADBLOCK_PROVIDERS line.

  python3 deploy/ad-provider-from-php.py f2187587a2.php
  python3 deploy/ad-provider-from-php.py --path /api/x/f2187587a2.js newer-file.php

WHY. Ad networks (HilltopAds, and others shipping the same client) hand a
publisher a PHP file to upload to the web root. Vidra runs no PHP: vidra-core
does that file's job itself (internal/httpapi/adproxy.go), configured by one
JSON value in the env file. So the PHP file is never deployed anywhere. Only a
handful of its fields matter (zone ids, key, API host and path), and when the
network issues a new file those are what changed.

Copying them by hand into a JSON string inside an env file is where this goes
wrong, and it goes wrong quietly: a missing quote does not stop the api from
booting, it logs one error, mounts nothing, and the ads simply stop. This
prints the line, validated, so an update is: run this, paste the line over the
old one in env/production.env, `vidra deploy`.

The JavaScript tag itself needs no attention: the api fetches a fresh one from
the network every few minutes. This is only for when the PHP FILE changes.

WHAT THIS ASSUMES, AND HOW IT FAILS. The proxy reproduces ONE client: it sends
zoneId, key, version and transport, and reads the tag from result.code of a
JSON answer. Whether a network only ever changes the file name and the key
between downloads is not something this repository can know. So the file's
logic is checked too: a file that sends other parameters, or reads the answer
differently, is REFUSED with the difference named. That is the moment to read
the new file and teach the proxy configuration (or the proxy) the change. It
is never the moment to paste a line that boots cleanly and serves nothing.

The PHP is read as TEXT. It is never executed and nothing is sent anywhere, so
this runs just as well on a laptop; it does not have to be on the server.

THE LOCAL PATH. --path is where the tag is served on this site. It must sit
under /api/ (Caddy forwards only /api/* and a fixed list of root paths to the
api, everything else answers 404 from the frontend) and outside /api/v1 (the
REST contract). It defaults to /api/x/<file name>.js, so a NEW file name gives
a NEW path, and that path is also written in the admin Custom JavaScript that
loads the tag. Pass --path with the path already in use to change the key
without touching that script.

ONE FILE, ONE PROVIDER. The value is a JSON array; for several networks, run
this per file and put the objects into one array by hand.

THE OUTPUT CONTAINS THE NETWORK KEY. It belongs in env/production.env (0600,
untracked) and nowhere else: not a ticket, not a commit, not a chat.

Exit codes:
  0  the line is on stdout
  1  not a recognisable anti-adblock client, or a value failed validation;
     stdout is empty so a redirect can never capture half a line
  2  usage error (argparse)
"""
import argparse
import json
import re
import sys
from pathlib import Path

# Every pattern is an allowlist. The values end up inside a single-quoted env
# value and then inside a URL the api requests, so anything that could close a
# quote or reshape the URL is refused rather than escaped.
ZONE = re.compile(r'\d+(-\d+)?')
KEY = re.compile(r'[A-Za-z0-9_-]{16,}')
HOST = re.compile(r'[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+')
URL_PATH = re.compile(r'/[A-Za-z0-9/_.-]*')
VERSION = re.compile(r'[0-9]+(\.[0-9]+)*')
USER_AGENT = re.compile(r'[A-Za-z0-9 ._/()-]{1,100}')
LOCAL_PATH = re.compile(r'/api/[A-Za-z0-9/_.-]+')


def field(source, name):
    """The string a `private $name = '...';` property is initialised with."""
    match = re.search(r'''private\s+\$%s\s*=\s*(['"])(.*?)\1\s*;''' % re.escape(name), source)
    return match.group(2) if match else None


CLIENT_PARAMS = {'zoneId', 'key', 'version', 'transport'}


def check_client(source):
    """Raise ValueError unless the file is the client the proxy reproduces."""
    request = re.search(r'array_merge\(\s*\$this->urlParams\s*,\s*array\((.*?)\)\s*\)', source, re.S)
    if not request:
        raise ValueError('cannot find the request it builds: this is not the client vidra-core reproduces')
    sent = set(re.findall(r'''['"]([A-Za-z_]+)['"]\s*=>''', request.group(1)))
    if sent != CLIENT_PARAMS:
        raise ValueError('it sends %s, but vidra-core reproduces a client that sends %s: the network changed '
                         'its client, so read the file before configuring anything'
                         % (', '.join(sorted(sent)) or 'no parameters', ', '.join(sorted(CLIENT_PARAMS))))
    if not re.search(r'''\[\s*['"]result['"]\s*\]\s*\[\s*['"]code['"]\s*\]''', source):
        raise ValueError('it no longer reads the tag from result.code of the answer: the network changed '
                         'its client, so read the file before configuring anything')


def provider(source, local_path):
    """Build the provider object, or raise ValueError naming what is wrong."""
    zone, key = field(source, 'zoneId'), field(source, 'key')
    host, path = field(source, 'domain'), field(source, 'path')
    if None in (zone, key, host, path):
        missing = [n for n, v in (('zoneId', zone), ('key', key), ('domain', host), ('path', path)) if v is None]
        raise ValueError('not an anti-adblock client: no $%s property' % ', $'.join(missing))
    check_client(source)
    version = field(source, 'version') or '1.0'
    agent = field(source, 'userAgent')
    for label, pattern, value in (('zone id', ZONE, zone), ('key', KEY, key), ('API host', HOST, host),
                                  ('API path', URL_PATH, path), ('version', VERSION, version)):
        if not pattern.fullmatch(value):
            # The key is a credential: say that it is wrong, never what it is.
            shown = '(hidden)' if label == 'key' else repr(value)
            raise ValueError('the %s in the file is not in the expected form: %s' % (label, shown))
    if agent is not None and not USER_AGENT.fullmatch(agent):
        raise ValueError('the user agent in the file is not in the expected form: %r' % agent)
    if not LOCAL_PATH.fullmatch(local_path) or local_path == '/api/v1' or local_path.startswith('/api/v1/'):
        raise ValueError('--path %r must be under /api/ and outside /api/v1 '
                         '(Caddy sends nothing else to the api)' % local_path)

    desktop, _, mobile = zone.partition('-')
    out = {
        'path': local_path,
        'upstream': 'https://%s%s' % (host, path),
        # transport is what the PHP client reports for its curl branch.
        'params': {'key': key, 'version': version, 'transport': '1'},
        'zone_param': 'zoneId',
        'zone_desktop': desktop,
    }
    if mobile:
        out['zone_mobile'] = mobile
    out['json_code_path'] = 'result.code'
    out['passthrough_query'] = True
    if agent:
        out['upstream_user_agent'] = agent
    return out


def main():
    parser = argparse.ArgumentParser(description='Print the AD_ANTIADBLOCK_PROVIDERS line for an anti-adblock PHP file.')
    parser.add_argument('php_file', type=Path, help='the PHP file from the ad network (read as text, never run)')
    parser.add_argument('--path', dest='local_path',
                        help='where this site serves the tag; default /api/x/<file name>.js')
    args = parser.parse_args()

    try:
        source = args.php_file.read_text(encoding='utf-8', errors='replace')
    except OSError as err:
        print('cannot read %s: %s' % (args.php_file, err.strerror), file=sys.stderr)
        return 1
    local_path = args.local_path or '/api/x/%s.js' % args.php_file.stem
    try:
        entry = provider(source, local_path)
    except ValueError as err:
        print('refused: %s' % err, file=sys.stderr)
        return 1

    print("AD_ANTIADBLOCK_PROVIDERS='%s'" % json.dumps([entry], separators=(',', ':')))
    print('served at %s: this must equal ANTI_ADBLOCK_PATH in the admin Custom JavaScript.' % local_path,
          file=sys.stderr)
    print('the line above contains the network key: put it in env/production.env only, then `vidra deploy`.',
          file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
