import contextlib
import http.client
import io
import socket
import threading
import unittest
from unittest.mock import Mock
from urllib.parse import urlsplit

from sealed_recovery_relay import readiness_relay


def request(endpoint, method='GET', path='/readyz'):
    origin = urlsplit(endpoint)
    connection = http.client.HTTPConnection(origin.hostname, origin.port, timeout=3)
    try:
        connection.request(method, path)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


class ReadinessRelayTests(unittest.TestCase):
    def assert_empty(self, result, expected):
        status, headers, body = result
        self.assertEqual(status, expected)
        self.assertEqual(body, b'')
        self.assertEqual(headers, {'Content-Length': '0', 'Connection': 'close'})

    def test_each_request_rechecks_changed_stale_and_recreated_backend(self):
        host = Mock()
        seen = []
        host.route, host.status = 'first', 200

        def readyz_status(*, timeout):
            seen.append((host.route, timeout))
            if host.route == 'stale':
                raise RuntimeError('PRIVATE_BACKEND_CANARY')
            return host.status

        host.readyz_status.side_effect = readyz_status
        with readiness_relay(host, port=0) as endpoint:
            self.assert_empty(request(endpoint), 200)
            host.status = 503
            self.assert_empty(request(endpoint), 503)
            host.route = 'stale'
            self.assert_empty(request(endpoint), 503)
            host.route, host.status = 'replacement', 200
            self.assert_empty(request(endpoint), 200)
        self.assertEqual(seen, [('first', 2), ('first', 2), ('stale', 2), ('replacement', 2)])

    def test_only_exact_integer_200_or_bounded_http_failures_are_exposed(self):
        host = Mock()
        with readiness_relay(host, port=0) as endpoint:
            for status in [200, 400, 401, 404, 429, 500, 503, 599]:
                with self.subTest(status=status):
                    host.readyz_status.return_value = status
                    self.assert_empty(request(endpoint), status)
            for status in [None, True, False, 200.0, '200', 99, 100, 199, 201, 204,
                           299, 300, 301, 302, 307, 308, 399, 600, 999, {}, []]:
                with self.subTest(status=status):
                    host.readyz_status.return_value = status
                    self.assert_empty(request(endpoint), 503)

    def test_other_paths_and_methods_are_empty_and_never_probe_backend(self):
        host = Mock()
        with readiness_relay(host, port=0) as endpoint:
            for path in ['/', '//readyz', '/readyz/', '/readyz?x=1', '/readyz#x',
                         '/api/v1/readyz', '/%72eadyz', 'http://localhost/readyz']:
                with self.subTest(path=path):
                    self.assert_empty(request(endpoint, path=path), 404)
            for method in ['HEAD', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'PATCH', 'PRIVATE_METHOD']:
                with self.subTest(method=method):
                    self.assert_empty(request(endpoint, method=method), 501)
        host.readyz_status.assert_not_called()

    def test_backend_exceptions_and_http_errors_never_log_private_values(self):
        host = Mock()
        host.readyz_status.side_effect = ValueError('PRIVATE_EXCEPTION_CANARY')
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with readiness_relay(host, port=0) as endpoint:
                self.assert_empty(request(endpoint), 503)
                self.assert_empty(request(endpoint, path='/PRIVATE_PATH_CANARY'), 404)
                self.assert_empty(request(endpoint, method='PRIVATE_METHOD_CANARY'), 501)
        self.assertEqual(stdout.getvalue(), '')
        self.assertEqual(stderr.getvalue(), '')

    def test_bind_conflict_aborts_before_context_or_backend(self):
        host = Mock()
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', 0))
            occupied.listen()
            with self.assertRaises(OSError):
                with readiness_relay(host, port=occupied.getsockname()[1]):
                    self.fail('must not enter context when bind fails')
        host.readyz_status.assert_not_called()

    def test_stalled_client_times_out_quietly_and_does_not_hold_listener(self):
        host = Mock()
        host.readyz_status.return_value = 200
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), readiness_relay(host, port=0) as endpoint:
            origin = urlsplit(endpoint)
            with socket.create_connection((origin.hostname, origin.port), timeout=3) as client:
                client.sendall(b'GET /readyz HTTP/1.1\r\n')
                self.assertEqual(client.recv(1), b'')
            host.readyz_status.assert_not_called()
            self.assert_empty(request(endpoint), 200)
        self.assertEqual(stderr.getvalue(), '')

    def test_normal_and_exception_exit_join_thread_and_release_socket(self):
        host = Mock()
        host.readyz_status.return_value = 200
        for fail in [False, True]:
            with self.subTest(command_error=fail):
                before = set(threading.enumerate())
                with contextlib.ExitStack() as stack:
                    if fail:
                        stack.enter_context(self.assertRaisesRegex(RuntimeError, 'command failed'))
                    with readiness_relay(host, port=0) as endpoint:
                        port = urlsplit(endpoint).port
                        self.assert_empty(request(endpoint), 200)
                        if fail:
                            raise RuntimeError('command failed')
                self.assertFalse(set(threading.enumerate()) - before)
                with readiness_relay(host, port=port) as endpoint:
                    self.assert_empty(request(endpoint), 200)


if __name__ == '__main__':
    unittest.main()
