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
# Anchored at the start of the tool name: `peertube_release_acceptance.py` and
# `recovery_release_acceptance.py` END with this text but take no --candidate
# (argparse rejects it), so an unanchored pattern would fail a correct v0.6.5
# migration or recovery runbook and tell its author to add a flag the tool
# refuses. `_` is a \w, so the lookbehind excludes both siblings while
# `tests/release_acceptance.py` still matches.
COMMAND = re.compile(r'(?<!\w)release_acceptance\.py\s+prepare\b')


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


def offenders(recipes):
    """Recipes that would silently prepare v0.6.4, as `<doc>:<line>`.

    Exempting a v0.6.4 record is the whole subtlety of the rule, so the
    predicate is a function with its own synthetic corpus: over the committed
    docs it is satisfied by exemption alone, and an inverted test or a widened
    exemption would still read green there.
    """
    return [f'{rel}:{lineno}' for rel, found in recipes.items() if 'v0.6.4' not in rel
            for lineno, block in found if '--candidate' not in block]


class DocsPrepareCandidateTests(unittest.TestCase):
    def test_the_extractor_reads_the_whole_continued_command_and_stops(self):
        text = ('prose\npython3 tests/release_acceptance.py prepare \\\n'
                '  --candidate docs/evidence/release-v0.6.5-verification/manifest.json \\\n'
                '  --out /tmp/handoff\nunrelated --candidate line\n')
        self.assertEqual([(n, '--candidate' in block) for n, block in prepare_recipes(text)], [(2, True)])
        self.assertNotIn('unrelated', next(prepare_recipes(text))[1])

    def test_the_sibling_drill_tools_are_not_mistaken_for_this_one(self):
        # `peertube_release_acceptance.py` and `recovery_release_acceptance.py`
        # take no --candidate: argparse REJECTS it. An unanchored pattern would
        # fail the validate lane on a correct v0.6.5 migration runbook, telling
        # its author to add a flag the tool refuses.
        for sibling in ('peertube_release_acceptance.py', 'recovery_release_acceptance.py'):
            with self.subTest(sibling=sibling):
                self.assertEqual(list(prepare_recipes(f'python3 tests/{sibling} prepare --out /tmp/h\n')), [])
        self.assertEqual([n for n, _ in prepare_recipes('python3 tests/release_acceptance.py prepare \\\n')], [1])

    def test_a_v065_record_offends_where_the_v064_record_is_exempt(self):
        self.assertEqual(offenders({'docs/r-v0.6.5.md': [(4, 'prepare \\')],
                                    'docs/r-v0.6.4.md': [(4, 'prepare \\')]}), ['docs/r-v0.6.5.md:4'])
        self.assertEqual(offenders({'docs/r-v0.6.5.md': [(4, 'prepare --candidate x \\')]}), [])

    def test_every_committed_prepare_recipe_outside_a_v064_record_names_its_candidate(self):
        recipes = {rel: list(prepare_recipes((REPO / rel).read_text())) for rel in tracked_docs()}
        self.assertTrue(any(recipes.values()), 'no prepare recipe found at all; the extractor has drifted')
        found = offenders(recipes)
        self.assertEqual(found, [], 'prepare recipes that would silently prepare the v0.6.4 '
                         'candidate; add --candidate docs/evidence/release-<tag>-verification/'
                         'manifest.json:\n' + '\n'.join(found))


if __name__ == '__main__':
    unittest.main()
