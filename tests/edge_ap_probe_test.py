"""tests/edge-ap-probe.sh tells an edge that interferes with ActivityPub apart
from an app that merely has federation off.

No network: the probe's CURL override points at a stub that answers from canned
rules, so every verdict below is the script's own decision about what it was
shown. The failure modes pinned here are the ones a CDN/WAF in front of an
instance causes silently: a challenge page served to a federation peer, an AP
representation cached without Vary: Accept, and an HTML request answered with
the cached AP JSON.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / 'edge-ap-probe.sh'
UUID = '11111111-2222-4333-8444-555555555555'

STUB = '''#!%s
import json, os, sys
argv = sys.argv[1:]
valued = {'-A', '-m', '--max-redirs', '-H', '-D', '-o', '-w', '-X', '-d', '--data', '--max-time'}
opts, positional, i = {}, [], 0
headers = []
while i < len(argv):
    a = argv[i]
    if a in valued:
        if a == '-H':
            headers.append(argv[i + 1])
        else:
            opts[a] = argv[i + 1]
        i += 2
    elif a.startswith('-'):
        i += 1
    else:
        positional.append(a)
        i += 1
url = positional[-1]
method = opts.get('-X', 'GET')
accept = ''
for h in headers:
    if h.lower().startswith('accept:'):
        accept = h.split(':', 1)[1].strip()
kind = 'ap' if ('activity+json' in accept or 'ld+json' in accept) else ('html' if 'text/html' in accept else 'any')
path = '/' + url.split('://', 1)[1].split('/', 1)[1] if '/' in url.split('://', 1)[1] else '/'
path = path.split('?', 1)[0]
with open(os.environ['STUB_LOG'], 'a') as f:
    f.write(method + ' ' + path + ' ' + kind + '\\n')
rule = {'status': 404, 'headers': {'Content-Type': 'text/plain'}, 'body': 'not found'}
for r in json.load(open(os.environ['STUB_RULES'])):
    if r['method'] == method and r['path'] == path and r.get('accept', kind) == kind:
        rule = r
        break
if rule.get('curl_exit'):
    sys.stderr.write('curl: (28) Operation timed out\\n')
    sys.exit(rule['curl_exit'])
with open(opts['-D'], 'w') as f:
    f.write('HTTP/1.1 %%d X\\r\\n' %% rule['status'])
    for k, v in rule['headers'].items():
        for one in (v if isinstance(v, list) else [v]):
            f.write('%%s: %%s\\r\\n' %% (k, one))
    f.write('\\r\\n')
with open(opts['-o'], 'w') as f:
    f.write(rule['body'])
sys.stdout.write(str(rule['status']))
''' % sys.executable

AP = {'Content-Type': 'application/activity+json; charset=utf-8', 'Vary': 'Accept'}
ACTOR = json.dumps({'@context': 'https://www.w3.org/ns/activitystreams', 'type': 'Person'})
HTML = {'Content-Type': 'text/html; charset=utf-8'}


def rule(method, path, status, headers, body, accept=None):
    r = {'method': method, 'path': path, 'status': status, 'headers': headers, 'body': body}
    if accept:
        r['accept'] = accept
    return r


def clean():
    rules = [
        rule('GET', '/.well-known/webfinger', 200, {'Content-Type': 'application/jrd+json'}, '{"subject":"acct:alice@example.test"}'),
        rule('GET', '/.well-known/nodeinfo', 200, {'Content-Type': 'application/json'}, '{"links":[]}'),
        rule('POST', '/inbox', 401, {'Content-Type': 'application/json'}, '{"error":{"code":"unauthorized"}}'),
    ]
    for p in ('/accounts/alice', '/videos/' + UUID, '/videos/watch/' + UUID):
        rules.append(rule('GET', p, 200, AP, ACTOR, 'ap'))
        rules.append(rule('GET', p, 200, HTML, '<!doctype html><html></html>', 'html'))
    return rules


class EdgeApProbeTests(unittest.TestCase):
    def run_probe(self, rules, *extra, base=True):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            stub = t / 'fakecurl'
            stub.write_text(STUB)
            stub.chmod(0o755)
            (t / 'rules.json').write_text(json.dumps(rules))
            env = dict(os.environ, CURL=str(stub), STUB_RULES=str(t / 'rules.json'), STUB_LOG=str(t / 'log'))
            args = ['bash', str(SCRIPT)]
            if base:
                args += ['--base-url', 'https://example.test']
            args += list(extra)
            p = subprocess.run(args, capture_output=True, text=True, env=env, timeout=60)
            log = (t / 'log').read_text().splitlines() if (t / 'log').exists() else []
            return p.returncode, p.stdout + p.stderr, log

    def full(self, rules):
        return self.run_probe(rules, '--account', 'alice', '--video', UUID)

    def test_clean_instance_passes_and_only_reads_plus_one_inbox_post(self):
        code, out, log = self.full(clean())
        self.assertEqual(code, 0, out)
        self.assertNotRegex(out, r'(?m)^FAIL')
        self.assertEqual([l.split()[0] for l in log if not l.startswith('GET')], ['POST'])
        self.assertEqual([l for l in log if l.startswith('POST')], ['POST /inbox ap'])

    def test_challenge_page_on_webfinger_fails(self):
        rules = [rule('GET', '/.well-known/webfinger', 403, dict(HTML, **{'cf-mitigated': 'challenge'}), '<html>Just a moment</html>')] + clean()
        code, out, _ = self.full(rules)
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r'FAIL.*webfinger.*edge challenges federation clients')

    def test_missing_vary_accept_fails(self):
        rules = [rule('GET', '/accounts/alice', 200, {'Content-Type': 'application/activity+json'}, ACTOR, 'ap')] + clean()
        code, out, _ = self.full(rules)
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r'FAIL.*Vary')

    def test_html_request_served_ap_json_fails(self):
        rules = [rule('GET', '/accounts/alice', 200, AP, ACTOR, 'html')] + clean()
        code, out, _ = self.full(rules)
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r'FAIL.*edge cached the AP representation')

    def test_video_pair_is_checked_when_asked(self):
        rules = [rule('GET', '/videos/watch/' + UUID, 200, {'Content-Type': 'application/activity+json'}, ACTOR, 'ap')] + clean()
        code, out, _ = self.full(rules)
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r'FAIL.*videos/watch.*Vary')

    def test_challenge_page_on_inbox_fails(self):
        rules = [rule('POST', '/inbox', 403, HTML, '<html>Attention Required</html>')] + clean()
        code, out, _ = self.full(rules)
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r'FAIL.*inbox')

    def test_federation_off_503_is_a_warning_not_a_failure(self):
        off = {'Content-Type': 'application/json', 'Vary': 'Accept'}
        body = '{"error":{"code":"federation_disabled","message":"federation is switched off on this instance"}}'
        rules = [
            rule('GET', '/accounts/alice', 503, off, body, 'ap'),
            rule('GET', '/videos/' + UUID, 503, off, body, 'ap'),
            rule('GET', '/videos/watch/' + UUID, 503, off, body, 'ap'),
            rule('POST', '/inbox', 503, off, body),
            rule('GET', '/.well-known/webfinger', 404, {'Content-Type': 'application/json'}, '{}'),
            rule('GET', '/.well-known/nodeinfo', 404, {'Content-Type': 'application/json'}, '{}'),
        ]
        code, out, _ = self.full(rules)
        self.assertEqual(code, 0, out)
        self.assertNotRegex(out, r'(?m)^FAIL')
        self.assertIn('WARN', out)
        self.assertIn('federation is off on this instance', out)

    def test_video_probes_the_federated_id_and_the_legacy_path(self):
        _, _, log = self.full(clean())
        self.assertIn('GET /videos/%s ap' % UUID, log)
        self.assertIn('GET /videos/watch/%s ap' % UUID, log)

    def vary(self, *values):
        h = dict(AP)
        h['Vary'] = list(values)
        return [rule('GET', '/accounts/alice', 200, h, ACTOR, 'ap')] + clean()

    def test_vary_accept_encoding_alone_fails(self):
        code, out, _ = self.full(self.vary('Accept-Encoding'))
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r'(?m)^FAIL.*Vary')

    def test_vary_lists_and_repeated_lines_pass(self):
        for values in (('Accept-Encoding, Accept',), ('Accept-Encoding', 'Accept'), ('Accept', 'Accept-Encoding'), ('*',)):
            code, out, _ = self.full(self.vary(*values))
            self.assertEqual(code, 0, (values, out))

    def test_ld_json_with_profile_is_an_ap_content_type(self):
        h = {'Content-Type': 'application/ld+json; profile="https://www.w3.org/ns/activitystreams"', 'Vary': 'Accept'}
        code, out, _ = self.full([rule('GET', '/accounts/alice', 200, h, ACTOR, 'ap')] + clean())
        self.assertEqual(code, 0, out)

    def test_actor_404_without_the_disabled_body_fails_and_names_the_causes(self):
        rules = [rule('GET', '/accounts/alice', 404, {'Content-Type': 'application/json'}, '{"error":"not found"}', 'ap')] + clean()
        code, out, _ = self.full(rules)
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r'(?m)^FAIL.*actor.*404.*unknown account.*edge interference.*v0\.7\.25')

    def test_pre_503_downgrades_the_404_to_a_warning(self):
        rules = [
            rule('GET', '/accounts/alice', 404, {'Content-Type': 'application/json'}, '{}', 'ap'),
            rule('POST', '/inbox', 404, {'Content-Type': 'application/json'}, '{}'),
        ] + clean()
        code, out, _ = self.run_probe(rules, '--account', 'alice', '--pre-503')
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r'(?m)^WARN.*actor.*--pre-503')
        self.assertRegex(out, r'(?m)^WARN.*inbox')
        code, out, _ = self.run_probe(rules, '--account', 'alice')
        self.assertEqual(code, 1, out)

    def test_inbox_redirect_fails(self):
        rules = [rule('POST', '/inbox', 301, {'Location': 'https://example.test/other'}, '')] + clean()
        code, out, _ = self.full(rules)
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r'(?m)^FAIL.*edge redirects the inbox')

    def test_inbox_redirect_with_an_html_body_is_still_a_redirect(self):
        rules = [rule('POST', '/inbox', 301, dict(HTML, Location='https://example.test/other'), '<html>Moved</html>')] + clean()
        code, out, _ = self.full(rules)
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r'(?m)^FAIL.*edge redirects the inbox')

    def test_help_names_the_old_release_vary_caveat(self):
        code, out, _ = self.run_probe(clean(), '--help')
        self.assertIn('Vary missing', out)

    def test_actor_401_json_is_a_signed_fetch_warning(self):
        rules = [rule('GET', '/accounts/alice', 401, {'Content-Type': 'application/json'}, '{"error":"signature required"}', 'ap')] + clean()
        code, out, _ = self.full(rules)
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r'(?m)^WARN.*signed fetch')

    def test_cf_mitigated_header_alone_is_a_challenge(self):
        rules = [rule('GET', '/.well-known/webfinger', 200, {'Content-Type': 'application/json', 'cf-mitigated': 'challenge'}, '{}')] + clean()
        code, out, _ = self.full(rules)
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r'(?m)^FAIL.*webfinger.*challenges')

    def test_challenge_on_nodeinfo_and_on_actor_fail(self):
        for r, pat in (
            (rule('GET', '/.well-known/nodeinfo', 200, HTML, '<html></html>'), r'(?m)^FAIL.*nodeinfo.*challenges'),
            (rule('GET', '/accounts/alice', 200, HTML, '<html></html>', 'ap'), r'(?m)^FAIL.*actor.*challenges'),
        ):
            code, out, _ = self.full([r] + clean())
            self.assertEqual(code, 1, out)
            self.assertRegex(out, pat)

    def test_inbox_html_answer_fails_even_with_a_non_403_status(self):
        rules = [rule('POST', '/inbox', 200, HTML, '<html>Checking your browser</html>')] + clean()
        code, out, _ = self.full(rules)
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r'(?m)^FAIL.*inbox.*challenges')

    def test_curl_failure_is_a_failure(self):
        rules = [{'method': 'GET', 'path': '/.well-known/nodeinfo', 'status': 0, 'headers': {}, 'body': '', 'curl_exit': 28}] + clean()
        code, out, _ = self.full(rules)
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r'(?m)^FAIL.*nodeinfo.*no response')

    def test_without_account_the_actor_checks_are_skipped_with_a_warning(self):
        code, out, log = self.run_probe(clean())
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r'(?m)^WARN.*actor checks skipped')
        self.assertNotIn('GET /accounts/alice ap', log)

    def test_help_does_not_print_shell_options(self):
        code, out, _ = self.run_probe(clean(), '--help')
        self.assertEqual(code, 0, out)
        self.assertIn('--pre-503', out)
        self.assertNotIn('set -euo', out)

    def test_base_url_is_required(self):
        code, out, log = self.run_probe(clean(), base=False)
        self.assertEqual(code, 2, out)
        self.assertIn('--base-url', out)
        self.assertEqual(log, [])


if __name__ == '__main__':
    unittest.main()
