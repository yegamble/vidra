"""Run the publisher's HTTP, digest, HLS and withdrawal checks in the meta suite."""

from pathlib import Path
import subprocess
import unittest


class ReferencePublisherTest(unittest.TestCase):
    def test_publisher(self):
        package = Path(__file__).resolve().parents[1] / "deploy/ipfs-reference/publisher"
        subprocess.run(["go", "test", "-count=1", "./..."], cwd=package, check=True, timeout=180)
