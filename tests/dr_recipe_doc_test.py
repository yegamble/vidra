"""The disaster-recovery recipe in deploy/README.md must create backups/
before it copies the fetched dump and config archive into it.

The recipe re-installs the release the dump was taken under (`--ref v0.7.5`),
and v0.7.5's provision.sh never creates /opt/vidra/backups (that arrived after
v0.7.5), nor does its bundle ship one. So step 4's
`install -m 0600 ... ~/dr/vidra-* backups/` failed for every dump taken today,
on the one night the recipe is followed (council ruling P0-5, infrastructure
F4). An `install -d` owned by the service user has to come first.
"""
from pathlib import Path
import re
import unittest

README = Path(__file__).resolve().parents[1] / 'deploy' / 'README.md'
HEADING = '### Disaster recovery: rebuild the host, in this order'


def dr_block():
    """The first ```bash fence after the DR heading, as a list of lines."""
    text = README.read_text()
    if HEADING not in text:
        raise AssertionError(f'deploy/README.md no longer has the heading {HEADING!r}')
    after = text.split(HEADING, 1)[1]
    match = re.search(r'```bash\n(.*?)\n```', after, re.S)
    if match is None:
        raise AssertionError('the DR section has no ```bash block')
    return match.group(1).splitlines()


def first(lines, pattern):
    for number, line in enumerate(lines):
        if not line.lstrip().startswith('#') and re.search(pattern, line):
            return number
    return None


class DisasterRecoveryRecipeTest(unittest.TestCase):
    COPY = r'\binstall -m 0600\b.*\bbackups/'
    MKDIR = r'\binstall -d -m 0700 -o vidra -g vidra /opt/vidra/backups\b'

    def test_backups_dir_is_created_before_the_copy_into_it(self):
        lines = dr_block()
        copy = first(lines, self.COPY)
        # Control: the copy this test is about is still in the block, so a
        # rewrite that drops or moves it fails here rather than passing vacuously.
        self.assertIsNotNone(copy, 'the DR block no longer copies into backups/')
        mkdir = first(lines, self.MKDIR)
        self.assertIsNotNone(mkdir, 'the DR block never creates /opt/vidra/backups')
        self.assertLess(mkdir, copy, 'backups/ is created AFTER the copy that needs it')


if __name__ == '__main__':
    unittest.main()
