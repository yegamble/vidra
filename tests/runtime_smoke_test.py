"""A03 must reject dirty, incomplete, or misleading runtime evidence."""
import copy
import unittest
from runtime_smoke import check_ledger, check_abort, check_runtime_ports


class RuntimeTests(unittest.TestCase):
    def test_ledger_requires_exact_version_and_clean_single_row(self):
        check_ledger('125|f\n', 125)
        for value in ('', '125|t', '124|f', '125|f\n125|f', '125|unknown'):
            with self.assertRaises(ValueError):
                check_ledger(value, 125)

    def test_abort_requires_real_failure_and_no_start_or_container_change(self):
        before = {'api': ['id', 'timestamp', 0]}
        check_abort(1, 'CORE MIGRATION FAILED', 'CORE', before, before)
        for code, log, after in ((0, 'CORE MIGRATION FAILED', before),
                                 (1, 'pull failed', before),
                                 (1, 'CORE MIGRATION FAILED\n4/6 start', before),
                                 (1, 'CORE MIGRATION FAILED', {})):
            with self.assertRaises(ValueError):
                check_abort(code, log, 'CORE', before, after)

    def test_runtime_ports_examine_actual_bindings(self):
        ports = {s: {} for s in ('postgres', 'redis', 'search')}
        for name, port in (('api', 8080), ('frontend', 3000)):
            ports[name] = {f'{port}/tcp': [{'HostIp': '127.0.0.1', 'HostPort': str(port)}]}
        check_runtime_ports(ports)
        bad = copy.deepcopy(ports)
        bad['postgres'] = {'5432/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '5432'}]}
        with self.assertRaises(ValueError):
            check_runtime_ports(bad)
        bad = copy.deepcopy(ports)
        bad['api']['8080/tcp'][0]['HostIp'] = '0.0.0.0'
        with self.assertRaises(ValueError):
            check_runtime_ports(bad)
