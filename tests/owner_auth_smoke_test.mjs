import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validateTarget, checkIdentity } from './owner-auth-smoke.mjs';

test('refuse non-rehearsal VM/project and incomplete A03', () => {
  const good = { status: 'PASS', project: 'vidra-a03-123-456', checks: { recovery: 'PASS' } };
  validateTarget('vidra-a02-123-456', good);
  for (const [vm, result] of [['production', good], ['vidra-a02-123-456', { ...good, status: 'FAIL' }],
    ['vidra-a02-123-456', { ...good, project: 'production' }]]) {
    assert.throws(() => validateTarget(vm, result));
  }
});

test('role readback must name the same persisted account', () => {
  checkIdentity({ id: 'owner', username: 'alice', role: 'admin' }, 'alice', 'admin');
  for (const user of [{ username: 'alice', role: 'admin' },
    { id: 'other', username: 'bob', role: 'admin' }, { id: 'owner', username: 'alice', role: 'user' }]) {
    assert.throws(() => checkIdentity(user, 'alice', 'admin'));
  }
});
