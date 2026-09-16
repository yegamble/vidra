import { test } from 'node:test';
import assert from 'node:assert/strict';
import { AwsV4Signer } from 'aws4fetch';
import { authorized, handle } from './worker.mjs';

const env = { ACCESS_KEY: 'test-key', SECRET_KEY: 'test-secret', REGION: 'us-east-005', BUCKET: 'private-media', PUBLIC_HOST: 'cdn.example.test', B2_ENDPOINT: 's3.us-east-005.backblazeb2.com' };
const url = 'https://cdn.example.test/private-media/video.mp4';
async function request({ method = 'GET', target = url, query = false, datetime, headers = {}, body } = {}) {
  const signed = await new AwsV4Signer({ url: target, method, headers, body,
    accessKeyId: env.ACCESS_KEY, secretAccessKey: env.SECRET_KEY, service: 's3', region: env.REGION,
    signQuery: query, datetime,
  }).sign();
  return new Request(signed.url, { method, headers: signed.headers, body, duplex: 'half' });
}
test('authenticated reads preserve byte ranges and stay on the fixed B2 origin', async () => {
  const input = await request({ headers: { Range: 'bytes=5-8' } });
  let calls = 0;
  const output = await handle(input, env, async (target, options) => {
    calls++;
    assert.equal(new URL(target).hostname, env.B2_ENDPOINT);
    assert.equal(options.headers.get('Range'), 'bytes=5-8');
    assert.equal(options.redirect, 'manual');
    assert.equal(options.cache, 'no-store');
    assert.deepEqual(options.cf.cacheTtlByStatus, { '100-599': -1 });
    const upstream = new Request(target, options);
    assert.equal(await authorized(upstream, env), true);
    return new Response('part', { status: 206, headers: { 'Content-Range': 'bytes 5-8/20' } });
  });
  assert.equal(calls, 1);
  assert.equal(output.status, 206);
  assert.equal(output.headers.get('Content-Range'), 'bytes 5-8/20');
  assert.equal(output.headers.get('Cache-Control'), 'private, no-store');
  assert.equal(await output.text(), 'part');
});
test('presigned query is verified before being converted to upstream auth', async () => {
  const input = await request({ query: true, target: url + '?response-content-type=video%2Fmp4&X-Amz-Expires=60' });
  assert.equal(await authorized(input, env), true);
  const output = await handle(input, env, async (target, options) => {
    assert.equal(new URL(target).searchParams.has('X-Amz-Signature'), false);
    assert.equal(new URL(target).searchParams.get('response-content-type'), 'video/mp4');
    assert.ok(options.headers.get('Authorization'));
    return new Response('video');
  });
  assert.equal(output.status, 200);
  const altered = new URL(input.url);
  altered.searchParams.set('response-content-type', 'text/html');
  assert.equal(await authorized(new Request(altered), env), false);
});
test('unsigned, tampered, expired, wrong bucket and wrong host never reach B2', async () => {
  const valid = await request();
  const expired = await request({ datetime: '20000101T000000Z', query: true });
  const inputs = [new Request(url), new Request(url + '?changed=1', valid), expired,
    await request({ target: 'https://cdn.example.test/other-bucket/video.mp4' }),
    await request({ target: 'https://other.example.test/private-media/video.mp4' })];
  for (const input of inputs) {
    const output = await handle(input, env, () => assert.fail('unauthorized origin call'));
    assert.equal(output.status, 403);
  }
});
test('streamed multipart parts and completion requests preserve the body', async () => {
  for (const method of ['PUT', 'POST']) {
    const input = await request({ method, target: url + '?partNumber=1&uploadId=fixture', body: 'payload', headers: { 'Content-Type': 'application/octet-stream' } });
    const output = await handle(input, env, async (target, options) => {
      assert.equal(await new Response(options.body).text(), 'payload');
      assert.equal(options.method, method);
      assert.equal(new URL(target).searchParams.get('uploadId'), 'fixture');
      return new Response(null, { status: 200 });
    });
    assert.equal(output.status, 200);
  }
});
test('object deletion is authenticated but bucket deletion is refused', async () => {
  const output = await handle(await request({ method: 'DELETE' }), env, async () => new Response(null, { status: 204 }));
  assert.equal(output.status, 204);
  const refused = await handle(await request({ method: 'DELETE', target: 'https://cdn.example.test/private-media' }), env, () => assert.fail('bucket deletion'));
  assert.equal(refused.status, 403);
});
test('an unsigned copy-source header cannot gain an upstream signature', async () => {
  const input = await request({ method: 'PUT', body: 'data' });
  const headers = new Headers(input.headers);
  headers.set('X-Amz-Copy-Source', '/private-media/another-object');
  const tampered = new Request(input, { headers });
  const output = await handle(tampered, env, () => assert.fail('unsigned copy source'));
  assert.equal(output.status, 403);
});
test('HEAD remains an authenticated HEAD and explicitly bypasses origin caching', async () => {
  const input = await request({ method: 'HEAD', headers: { 'X-Amz-Content-Sha256': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855' } });
  const output = await handle(input, env, async (target, options) => {
    assert.equal(options.method, 'HEAD');
    assert.equal(options.cache, 'no-store');
    assert.equal(options.cf.cacheTtl, undefined);
    assert.equal(options.cf.cacheTtlByStatus['100-599'], -1);
    assert.equal(await authorized(new Request(target, options), env), true);
    return new Response(null, { headers: { 'Content-Length': '42' } });
  });
  assert.equal(output.status, 200);
  assert.equal(output.headers.get('Content-Length'), '42');
});
