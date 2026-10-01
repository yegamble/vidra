"""env/*.env.example must pin the tags of the NEWEST recorded release.

The manual path (copy env/production.env.example, fill the secrets, run
deploy.sh) deploys exactly the three VIDRA_*_TAG lines in the template. Nothing
bumped them when a release was cut, so the template sat on v0.7.3 while
releases/v0.7.5.json (core v0.7.5, user v0.7.3, search v0.7.3) was current: an
operator who followed the docs to the letter shipped an old release, the deploy
exited 0, and no check said otherwise (the ledger assertion compares the pinned
checkout against itself).

THIS TEST IS THE FORCING FUNCTION. Cutting a release adds releases/<tag>.json
and nothing in deploy/release.sh edits the templates, so the release PR goes
red here until it also bumps the three lines in every template that pins them
(env/production.env.example and env/staging.env.example today). That is
deliberate: the bump is a diff-visible part of the release, not a follow-up
somebody forgets. Newest is by semver of the record's `release`, read through
deploy/release-mapping.py's own load_records, so a malformed record fails here
the same way it fails the deploy preflight.

Templates that pin none of the three keys (local, qa, dev-remote build from
source) are out of scope; a template that pins SOME but not all is a defect.
"""
import importlib.util
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent.parent
KEYS = ('VIDRA_CORE_TAG', 'VIDRA_USER_TAG', 'VIDRA_SEARCH_TAG')
ROLES = {'VIDRA_CORE_TAG': 'core', 'VIDRA_USER_TAG': 'user', 'VIDRA_SEARCH_TAG': 'search'}

_spec = importlib.util.spec_from_file_location('release_mapping', ROOT / 'deploy/release-mapping.py')
mapping = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mapping)


def newest_record():
    records, problems = mapping.load_records(ROOT / 'releases')
    assert not problems, problems
    assert records, 'releases/ holds no records'
    return max(records, key=lambda record: mapping.semver(record['release']))


def pins(path):
    """KEY -> value for the uncommented KEY=value lines; the LAST one wins, as
    deploy/lib.sh's env_get does."""
    found = {}
    for line in path.read_text().splitlines():
        match = re.fullmatch(r'\s*(VIDRA_(?:CORE|USER|SEARCH)_TAG)\s*=\s*(\S*)\s*', line)
        if match:
            found[match.group(1)] = match.group(2)
    return found


class EnvTemplatePins(unittest.TestCase):
    def test_pinning_templates_match_the_newest_release_record(self):
        record = newest_record()
        want = {key: record['components'][role]['tag'] for key, role in ROLES.items()}
        checked = []
        for template in sorted((ROOT / 'env').glob('*.env.example')):
            have = pins(template)
            if not have:
                continue
            checked.append(template.name)
            self.assertEqual(
                set(have), set(KEYS),
                f'{template.name} pins {sorted(have)} but a template must pin all of {list(KEYS)}')
            self.assertEqual(
                have, want,
                f'{template.name} pins {have} but the newest release record '
                f'(releases/{record["release"]}.json) pairs {want}. A manual-path operator who '
                'copies this template deploys the older release. Bump the template in the same '
                'PR that adds the record.')
        self.assertIn('production.env.example', checked)
        self.assertIn('staging.env.example', checked)


if __name__ == '__main__':
    unittest.main()
