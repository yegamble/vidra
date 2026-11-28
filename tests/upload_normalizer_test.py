import importlib.util
import io
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch


module = Path(__file__).resolve().parents[1] / 'deploy/upload-normalizer.py'
spec = importlib.util.spec_from_file_location('upload_normalizer', module)
broker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(broker)


class NormalizerTests(unittest.TestCase):
    def request(self, headers, body=b''):
        client, server = socket.socketpair()
        self.addCleanup(client.close)
        def handle():
            with server:
                broker.Handler(server, ('local', 0), None)
        worker = threading.Thread(target=handle)
        worker.start()
        client.settimeout(5)
        client.sendall(b'POST /normalize HTTP/1.0\r\n' + headers + b'\r\n\r\n' + body)
        with client.makefile('rb') as stream:
            result = stream.read()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        return result

    def test_refuses_invalid_input_before_opening_private_storage(self):
        for header, status in [(b'Content-Length: 21474836481', 413),
                               (b'Content-Length: 0', 413),
                               (b'Content-Length: 3\r\nContent-Length: 3', 400),
                               (b'Transfer-Encoding: chunked', 400)]:
            with self.subTest(header=header):
                self.assertIn(str(status).encode(), self.request(header).splitlines()[0])

    def test_only_finished_output_is_returned_and_staging_is_removed(self):
        def encode(work, image, connection):
            self.assertEqual((work / 'source').read_bytes(), b'input')
            result = work / 'processed.mp4'
            result.write_bytes(b'processed')
            return result
        with tempfile.TemporaryDirectory() as tmp, patch.object(broker, 'WORK', Path(tmp)), \
            patch.object(broker, 'core_image', return_value='fixture'), \
            patch.object(broker, 'reap'), patch.object(broker, 'remove_encoder'), \
            patch.object(broker.shutil, 'disk_usage', return_value=broker.shutil._ntuple_diskusage(1 << 40, 0, 1 << 40)), \
            patch.object(broker, 'run_encoder', side_effect=encode) as runner:
            response = self.request(b'Content-Length: 5', b'input')
            self.assertEqual(response.split(b'\r\n\r\n', 1)[1], b'processed')
            self.assertEqual(list(Path(tmp).glob('job-*')), [])
            runner.side_effect = ValueError('invalid video')
            self.assertIn(b'422', self.request(b'Content-Length: 5', b'input').splitlines()[0])
            self.assertEqual(list(Path(tmp).glob('job-*')), [])

    def test_reap_only_removes_verified_stale_jobs(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(broker, 'WORK', Path(tmp)):
            stale = Path(tmp) / ('job-' + '0' * 24)
            stale.mkdir()
            (stale / 'source').write_bytes(b'private')
            with patch.object(broker.subprocess, 'check_output', side_effect=[b'a' * 64, b'']), \
                    patch.object(broker.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)) as remove:
                broker.reap()
                self.assertEqual(remove.call_args.args[0], ['/usr/bin/docker', 'rm', '-f', 'a' * 64])
            self.assertFalse(stale.exists())
            unexpected = Path(tmp) / 'job-other'
            unexpected.mkdir()
            with self.assertRaises(ValueError):
                broker.reap()
            self.assertTrue(unexpected.exists())

    def test_refuses_short_request(self):
        with self.assertRaises(EOFError):
            broker.copy_request(io.BytesIO(b'123'), io.BytesIO(), 4)
