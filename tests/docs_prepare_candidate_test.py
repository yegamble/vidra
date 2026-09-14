"""A `release_acceptance.py prepare` recipe must name the candidate it prepares.

`prepare` falls back to the committed v0.6.4 manifest when `--candidate` is
omitted, so a block copied into a newer record silently prepares the OLD
release and then refuses that release's correctly named bucket. A v0.6.4 record
is the one place the default IS the documented release; everywhere else the
flag has to be on the page. Nothing here skips: `git ls-files` failing fails
the test.
"""
from pathlib import Path
import re
import subprocess
import unittest

REPO = Path(__file__).resolve().parents[1]
COMMAND = re.compile(r'release_acceptance\.py\s+prepare\b')


def tracked_docs():
    out = subprocess.run(['git', 'ls-files', '--', 'docs/*.md', 'docs/**/*.md'],
                         cwd=REPO, capture_output=True, text=True, check=True).stdout
    return sorted(set(line for line in out.splitlines() if line))


def prepare_recipes(text):
    r"""Each prepare command, with the `\`-continued lines that belong to it."""
    lines = text.splitlines()
    for n, line in enumerate(lines):
        if COMMAND.search(line):
            block = [line]
            while block[-1].rstrip().endswith('\\') and n + len(block) < len(lines):
                block.append(lines[n + len(block)])
            yield n + 1, '\n'.join(block)


class DocsPrepareCandidateTests(unittest.TestCase):
    def test_the_extractor_reads_the_whole_continued_command_and_stops(self):
        text = ('prose\npython3 tests/release_acceptance.py prepare \\\n'
                '  --candidate docs/evidence/release-v0.6.5-verification/manifest.json \\\n'
                '  --out /tmp/handoff\nunrelated --candidate line\n')
        self.assertEqual([(n, '--candidate' in block) for n, block in prepare_recipes(text)], [(2, True)])
        self.assertNotIn('unrelated', next(prepare_recipes(text))[1])

    def test_every_committed_prepare_recipe_outside_a_v064_record_names_its_candidate(self):
        recipes = {rel: list(prepare_recipes((REPO / rel).read_text())) for rel in tracked_docs()}
        self.assertTrue(any(recipes.values()), 'no prepare recipe found at all; the extractor has drifted')
        offenders = [f'{rel}:{lineno}' for rel, found in recipes.items() if 'v0.6.4' not in rel
                     for lineno, block in found if '--candidate' not in block]
        self.assertEqual(offenders, [], 'prepare recipes that would silently prepare the v0.6.4 '
                         'candidate; add --candidate docs/evidence/release-<tag>-verification/'
                         'manifest.json:\n' + '\n'.join(offenders))


if __name__ == '__main__':
    unittest.main()
