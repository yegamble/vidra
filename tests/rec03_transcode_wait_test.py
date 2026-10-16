"""Published video state cannot substitute for completion of its whole ladder."""
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('rec03-upgrade-rollback.sh')
VIDEO = '12345678-1234-1234-1234-123456789abc'


def run_gate(responses, video=VIDEO, read_error=False):
    text = SCRIPT.read_text().split('# >>> BEGIN transcode drain gate', 1)[1].split('\n', 1)[1].split('# <<< END transcode drain gate', 1)[0]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / 'rows').write_text('\n'.join(responses) + '\n')
        script = f'''set -uo pipefail
cd {shlex.quote(tmp)}
log() {{ :; }}
die() {{ echo "$*" >&2; exit 1; }}
sleep() {{ echo sleep >> sleeps; }}
psq() {{
  echo "$1" >> queries
  {'return 1' if read_error else 'sed -n "1p" rows; test $(wc -l < rows) -eq 1 || sed -i "1d" rows;'}
}}
{text}
wait_transcodes {shlex.quote(video)}
'''
        result = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
        queries = (root / 'queries').read_text().splitlines() if (root / 'queries').exists() else []
        sleeps = (root / 'sleeps').read_text().splitlines() if (root / 'sleeps').exists() else []
        return result, queries, sleeps


class TranscodeDrain(unittest.TestCase):
    def test_waits_through_empty_queue_and_partial_ladder_until_every_job_done(self):
        result, queries, sleeps = run_gate(['0:0:0', '7:1:0', '7:6:0', '7:7:0'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(queries), 4)
        self.assertEqual(len(sleeps), 3)
        for query in queries:
            self.assertIn(f"FROM transcode_jobs WHERE video_id = '{VIDEO}'", query)
            self.assertIn("state = 'done'", query)
            self.assertIn("state = 'failed'", query)

    def test_terminal_failure_and_unreadable_or_malformed_counts_refuse(self):
        for rows, read_error in [(['7:6:1'], False), ([''], False), (['garbage'], False), (['7:7:0'], True)]:
            with self.subTest(rows=rows, read_error=read_error):
                result, _, sleeps = run_gate(rows, read_error=read_error)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(sleeps, [])

    def test_incomplete_queue_times_out_even_if_video_was_already_published(self):
        result, queries, sleeps = run_gate(['7:6:0'])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('600 seconds', result.stderr)
        self.assertEqual(len(queries), 120)
        self.assertEqual(len(sleeps), 120)

    def test_hostile_id_is_rejected_before_any_database_call(self):
        result, queries, _ = run_gate(['1:1:0'], video="x'; DROP TABLE users; --")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(queries, [])

    def test_real_upload_phases_wait_before_baseline_and_worker_verdict(self):
        text = SCRIPT.read_text()
        data = text.split('\ndata)\n', 1)[1].split('\nfp)\n', 1)[0]
        split = text.split('\nsplit)\n', 1)[1].split('\nreport)\n', 1)[0]
        self.assertLess(data.index('wait_transcodes "$vid"'), data.index('fingerprint |'))
        self.assertLess(split.index('wait_transcodes "$vid"'), split.index('who transcoded it'))


if __name__ == '__main__':
    unittest.main()
