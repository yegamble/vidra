import { AwsV4Signer } from 'aws4fetch';

const cors = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
  'Access-Control-Allow-Headers': 'Range, Content-Type',
  'Access-Control-Expose-Headers': 'Content-Length, Content-Range, Accept-Ranges, ETag',
  'Cache-Control': 'private, no-store',
};
const reject = (status = 403) => new Response(null, { status, headers: cors });
const equal = (a, b) => {
  if (!/^[a-f0-9]{64}$/.test(a) || !/^[a-f0-9]{64}$/.test(b)) return false;
  let diff = 0;
  for (let i = 0; i < 64; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
};

// Verify the caller's signature before using the bucket credential at the
// origin. An unsigned "private bucket proxy" would publish every private video.
export async function authorized(request, env, now = Date.now()) {
  const url = new URL(request.url);
  const query = url.searchParams;
  const auth = request.headers.get('Authorization');
  const presigned = query.has('X-Amz-Signature');
  if (auth && presigned) return false;
  if ([...query.keys()].length !== new Set(query.keys()).size) return false;
  let credential, signedHeaders, signature, datetime, lifetime;
  if (presigned) {
    if (!['GET', 'HEAD'].includes(request.method)) return false;
    if (query.get('X-Amz-Algorithm') !== 'AWS4-HMAC-SHA256') return false;
    credential = query.get('X-Amz-Credential');
    signedHeaders = query.get('X-Amz-SignedHeaders');
    signature = query.get('X-Amz-Signature');
    datetime = query.get('X-Amz-Date');
    const expires = query.get('X-Amz-Expires');
    if (!/^\d+$/.test(expires || '')) return false;
    lifetime = Number(expires) * 1000;
    if (lifetime < 1000 || lifetime > 604800000) return false;
    query.delete('X-Amz-Signature');
  } else {
    const match = /^AWS4-HMAC-SHA256 Credential=([^,]+),\s*SignedHeaders=([^,]+),\s*Signature=([a-f0-9]{64})$/.exec(auth || '');
    if (!match) return false;
    [, credential, signedHeaders, signature] = match;
    datetime = request.headers.get('X-Amz-Date');
    lifetime = 900000;
  }
  if (!/^\d{8}T\d{6}Z$/.test(datetime || '')) return false;
  const stamp = Date.parse(datetime.replace(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/, '$1-$2-$3T$4:$5:$6Z'));
  if (!Number.isFinite(stamp) || now < stamp - 300000 || now > stamp + lifetime) return false;
  if (credential !== `${env.ACCESS_KEY}/${datetime.slice(0, 8)}/${env.REGION}/s3/aws4_request`) return false;
  const names = (signedHeaders || '').split(';');
  if (!names.includes('host') || new Set(names).size !== names.length || names.some(n => !/^[a-z0-9-]+$/.test(n))) return false;
  if (names.join(';') !== [...names].sort().join(';')) return false;
  if (!presigned && (!names.includes('x-amz-date') || !names.includes('x-amz-content-sha256'))) return false;
  // Do not let an unsigned copy-source or metadata header gain the Worker's
  // upstream signature. S3 requires its x-amz-* headers to be authenticated.
  if ([...request.headers.keys()].some(n => n.startsWith('x-amz-') && !names.includes(n))) return false;
  const headers = new Headers();
  for (const name of names) {
    if (name === 'host') continue;
    if (!request.headers.has(name)) return false;
    headers.set(name, request.headers.get(name));
  }
  const payload = request.headers.get('X-Amz-Content-Sha256');
  // Changing the upstream host changes a streaming signature's seed. Refuse
  // that unsupported format instead of accepting an unverifiable upload.
  if (payload && payload !== 'UNSIGNED-PAYLOAD' && !/^[a-f0-9]{64}$/.test(payload)) return false;
  if (presigned && payload && !names.includes('x-amz-content-sha256')) return false;
  const signer = new AwsV4Signer({
    url: url.href, method: request.method, headers,
    accessKeyId: env.ACCESS_KEY, secretAccessKey: env.SECRET_KEY,
    service: 's3', region: env.REGION, datetime, signQuery: presigned, allHeaders: true,
  });
  if (signer.signedHeaders !== signedHeaders) return false;
  return equal(signature, await signer.signature());
}

export async function handle(request, env, originFetch = fetch) {
  try {
    const url = new URL(request.url);
    if (url.protocol !== 'https:' || url.hostname !== env.PUBLIC_HOST) return reject();
    if (!/^s3\.[a-z0-9-]+\.backblazeb2\.com$/.test(env.B2_ENDPOINT)) return reject(503);
    if (url.pathname !== `/${env.BUCKET}` && !url.pathname.startsWith(`/${env.BUCKET}/`)) return reject();
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });
    if (!['GET', 'HEAD', 'PUT', 'POST', 'DELETE'].includes(request.method)) return reject(405);
    // Buckets are provisioned separately; the bridge must never create/delete one.
    if (['PUT', 'DELETE'].includes(request.method) && url.pathname.replace(/\/$/, '') === `/${env.BUCKET}`) return reject();
    if (!await authorized(request, env)) return reject();
    url.hostname = env.B2_ENDPOINT;
    for (const name of [...url.searchParams.keys()]) {
      if (name.startsWith('X-Amz-')) url.searchParams.delete(name);
    }
    const headers = new Headers();
    for (const [name, value] of request.headers) {
      if (name.startsWith('x-amz-') || ['content-type', 'content-length', 'content-md5', 'range', 'if-match', 'if-none-match', 'if-modified-since', 'if-unmodified-since'].includes(name)) headers.set(name, value);
    }
    headers.delete('x-amz-date');
    const signed = await new AwsV4Signer({
      url: url.href, method: request.method, headers, body: request.body,
      accessKeyId: env.ACCESS_KEY, secretAccessKey: env.SECRET_KEY,
      service: 's3', region: env.REGION,
    }).sign();
    const response = await originFetch(signed.url.href, {
      method: signed.method, headers: signed.headers, body: request.body,
      // A zero TTL still forces caching and can turn HEAD into an origin GET,
      // invalidating its SigV4 method. Bypass the cache, including on misses.
      redirect: 'manual', duplex: 'half', cache: 'no-store',
      cf: { cacheTtlByStatus: { '100-599': -1 }, cacheEverything: false },
    });
    // A redirect would send the viewer outside Cloudflare or expose credentials.
    if (response.status >= 300 && response.status < 400 && response.status !== 304) return reject(502);
    const outputHeaders = new Headers(response.headers);
    for (const [name, value] of Object.entries(cors)) outputHeaders.set(name, value);
    outputHeaders.set('X-Vidra-Storage-Route', 'cloudflare-b2');
    return new Response(response.body, { status: response.status, headers: outputHeaders });
  } catch {
    // Never log signed URLs, headers, credentials, or provider error bodies.
    return reject(502);
  }
}

export default { fetch: (request, env) => handle(request, env) };
