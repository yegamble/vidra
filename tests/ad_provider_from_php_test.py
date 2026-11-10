#!/usr/bin/env python3
"""deploy/ad-provider-from-php.py: an ad network's PHP file in, one env line out.

The line is consumed by vidra-core's ad proxy, which decodes it strictly: an
unknown key or malformed JSON disables the feature with a logged error and no
other symptom. So these tests hold the output to the proxy's own field names,
and hold a refusal to "nothing on stdout" so a redirect cannot capture half a
line into an env file.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'deploy' / 'ad-provider-from-php.py'

# The json tags of adProxyProvider in vidra-core internal/httpapi/adproxy.go.
# The proxy refuses any other key (DisallowUnknownFields).
PROXY_FIELDS = {'path', 'upstream', 'params', 'zone_param', 'zone_desktop', 'zone_mobile', 'passthrough_query',
                'json_code_path', 'content_type', 'upstream_user_agent', 'cache_ttl_seconds'}

FAKE_KEY = 'FAKEKEYFAKEKEYFAKEKEY0000'


REQUEST = """    private function getPath($transport) {
        $queryParams = array_merge($this->urlParams, array(
                    'zoneId'    => $this->getZoneId(),
                    'key'       => $this->key,
                    'version'   => $this->version,
                    'transport' => $transport%s
        ));
        return $this->path . '?' . http_build_query($queryParams);
    }"""
ANSWER = """        if (isset($response['result']['code'])) {
            $result = $response['result']['code'];
        }"""


def php(zone="'111-222'", key="'%s'" % FAKE_KEY, domain="'api.adnetwork.example'", extra='',
        request=REQUEST % '', answer=ANSWER):
    lines = ['<?php', 'class AntiAdBlock {']
    for name, value in (('zoneId', zone), ('key', key), ('domain', domain)):
        if value is not None:
            lines.append('    private $%s = %s;' % (name, value))
    lines += ["    private $path = '/publisher/antiAdBlock';", "    private $version = '1.0';",
              "    private $userAgent = 'AdNetwork Anti-AdBlock Client/1.0';", request, answer, extra, '}']
    return '\n'.join(lines)


class AdProviderFromPhp(unittest.TestCase):
    def run_script(self, source, *args, name='f2187587a2.php'):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / name
            path.write_text(source)
            return subprocess.run([sys.executable, str(SCRIPT), *args, str(path)], capture_output=True, text=True)

    def entry(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 1, 'exactly one line, so it can be pasted over the old one')
        prefix, suffix = "AD_ANTIADBLOCK_PROVIDERS='", "'"
        self.assertTrue(lines[0].startswith(prefix) and lines[0].endswith(suffix), lines[0])
        value = lines[0][len(prefix):-len(suffix)]
        self.assertNotIn("'", value, 'a quote inside would end the env value early')
        providers = json.loads(value)
        self.assertEqual(len(providers), 1)
        return providers[0]

    def test_the_line_carries_what_the_php_file_did(self):
        entry = self.entry(self.run_script(php()))
        self.assertEqual(entry, {
            'path': '/api/x/f2187587a2.js',
            'upstream': 'https://api.adnetwork.example/publisher/antiAdBlock',
            'params': {'key': FAKE_KEY, 'version': '1.0', 'transport': '1'},
            'zone_param': 'zoneId',
            'zone_desktop': '111',
            'zone_mobile': '222',
            'json_code_path': 'result.code',
            'passthrough_query': True,
            'upstream_user_agent': 'AdNetwork Anti-AdBlock Client/1.0',
        })

    def test_only_fields_the_proxy_accepts_are_emitted(self):
        self.assertLessEqual(set(self.entry(self.run_script(php()))), PROXY_FIELDS)

    def test_a_single_zone_has_no_mobile_zone(self):
        entry = self.entry(self.run_script(php(zone="'333'")))
        self.assertEqual(entry['zone_desktop'], '333')
        self.assertNotIn('zone_mobile', entry)

    def test_path_keeps_the_address_the_custom_script_already_loads(self):
        result = self.run_script(php(), '--path', '/api/x/old-name.js', name='brand-new-name.php')
        self.assertEqual(self.entry(result)['path'], '/api/x/old-name.js')
        self.assertIn('/api/x/old-name.js', result.stderr)

    def test_a_path_the_api_would_never_receive_is_refused(self):
        for bad in ('/f2187587a2.js', '/api/v1/x.js', '/api/v1', '/api/x/a b.js', "/api/x/a'.js"):
            result = self.run_script(php(), '--path', bad)
            self.assertEqual(result.returncode, 1, bad)
            self.assertEqual(result.stdout, '', bad)
            self.assertIn('/api/', result.stderr)

    def test_a_file_that_is_not_the_client_is_refused(self):
        result = self.run_script(php(key=None))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertIn('$key', result.stderr)

    def test_values_that_could_reshape_the_request_are_refused(self):
        for kwargs in ({'domain': "'api.example/x?y='"}, {'domain': "'api.example\"'"}, {'zone': "'12;34'"},
                       {'key': "'short'"}):
            result = self.run_script(php(**kwargs))
            self.assertEqual(result.returncode, 1, kwargs)
            self.assertEqual(result.stdout, '', kwargs)

    # The proxy reproduces one client. If the network ships a file that asks or
    # answers differently, a line built from it would boot and serve nothing.
    def test_a_client_that_sends_another_parameter_is_refused_by_name(self):
        result = self.run_script(php(request=REQUEST % ",\n                    'signature' => $this->sign()"))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertIn('signature', result.stderr)

    def test_a_client_that_reads_the_answer_differently_is_refused(self):
        moved = ANSWER.replace("['result']['code']", "['data']['script']")
        result = self.run_script(php(answer=moved))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertIn('result.code', result.stderr)

    def test_a_refused_key_is_never_echoed(self):
        result = self.run_script(php(key="'bad key with spaces 0123456789'"))
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('bad key', result.stdout + result.stderr)

    def test_the_file_is_read_not_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'ran'
            source = php(extra="    // <?php system('touch %s'); ?>" % marker)
            self.entry(self.run_script(source))
            self.assertFalse(marker.exists())


if __name__ == '__main__':
    unittest.main()
