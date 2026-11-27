# Restore a frozen PeerTube source after a Vidra cutover

Use this procedure to verify an old PeerTube disk image while Vidra serves the public site. It covers the case where the source was frozen with a PostgreSQL database-specific role setting, a write refusal at nginx and paused BullMQ workers. A saved disk includes the local database and artwork. External media buckets, DNS, firewall rules, public addresses and independent backup keys have separate recovery paths.

## Boot one isolated copy

1. Record the expected image, source owner, region, minimum disk size, frozen export digest, database fingerprint and saved queue state. Select a new recovery guest. Identify the current writer and frozen incumbent in the operator inventory so neither can be selected as the test target.
2. Establish the network policy **before boot**. On DigitalOcean, create a dedicated empty, unpeered VPC and a unique tag. Apply that tag to a cloud firewall with one SSH rule for the approved operator address and an empty outbound rule list. Read the provider configuration back and check for any other firewall attached to the tag. Supply the VPC and tag in the creation request. A guest firewall that starts later allows services to run before the policy is in force. [DigitalOcean cloud firewall rules](https://docs.digitalocean.com/products/networking/firewalls/how-to/configure-rules/) · [Firewall tags at creation](https://docs.digitalocean.com/products/networking/firewalls/how-to/create/)
3. Wait for the provider's create **action** to complete. Pending firewall association and temporary API errors need bounded retries while the isolation policy remains installed. Record the first failure before cleanup. Confirm the actual guest ID, disk image, VPC, tag, applied firewall and operator SSH host-key trust. Keep public DNS on Vidra.
4. Before starting or adjusting the application, hash the frozen database export and check its table of contents with `pg_restore --list`. Compare a consistent read of the restored database with the frozen counts and fingerprint. A physical row-version fingerprint is comparable on a disk clone. For a logical restore, use stable primary keys and a canonical row digest. Hash representative local avatars, thumbnails and storyboards against independently recorded original values.
5. Confirm PostgreSQL's application role returns `on` for `SHOW default_transaction_read_only` in a fresh connection. Check the saved queue pause flags and active counts, including delivery queues if the exercise will temporarily allow database writes. Preserve the nginx method fence. Test a local login POST without credentials and verify its expected 503 and `Retry-After` value. Keep SMTP, federation delivery and external object storage isolated.

## Cold-start PeerTube 8.3.1 under the restored fence

PeerTube 8.3.1 executes `CREATE FUNCTION` during `initDatabaseModels`. On the restored cloud image, PostgreSQL rejected that startup statement and the application restarted repeatedly. nginx still refused writes, but its upstream could not answer configuration reads. An already-running source can therefore pass read-only checks that fail on a fresh boot. [Restore evidence and test scope](evidence/peertube-frozen-source-2026-11-27.md)

Use the following sequence **on the isolated disposable guest** after preserving the frozen data evidence. If a writable connection could reach real users, mail or federation, keep the application stopped. Back up the original role setting and queue state. Use the installation's established queue tooling to pause all work for the startup exercise and verify zero active jobs.

1. Stop the restarting PeerTube service. Keep PostgreSQL, Redis, the provider fence and nginx running. Select the application role and database from the private operator inventory. In the following SQL, supply the `psql` variables `app_role` and `app_db` to a local PostgreSQL administrator. Confirm the application role is ordinary and the operator is connected to the expected disposable database.
2. Prepare the restoration of the scoped role setting before opening the startup window. For this tested setting, the cleanup statement is `ALTER ROLE :"app_role" IN DATABASE :"app_db" SET default_transaction_read_only = on`. The operator running the sequence should arrange for it to execute on success, timeout or interruption. Following an unexpected restart, recheck it under network isolation.
3. Permit startup for that role in that database only, then start the existing PeerTube service. Use a bounded loopback readiness check. Pin the source hostname to loopback with normal TLS validation at nginx. Check the exact HTTP status and configured version at `/api/v1/config`.

   ```sql
   ALTER ROLE :"app_role" IN DATABASE :"app_db"
       SET default_transaction_read_only = off;
   ```

4. As soon as the application is ready, or when the timeout expires, reinstate the original read-only setting. Record the database server timestamp **after** that change commits. The PeerTube connection pool can retain writable sessions established earlier. In a local administrator session using `psql`, retire only idle application connections opened before the boundary. Use autocommit so each poll sees current session state.

   ```sql
   ALTER ROLE :"app_role" IN DATABASE :"app_db"
       SET default_transaction_read_only = on;
   SELECT clock_timestamp() AS fence_time \gset

   SELECT pg_terminate_backend(pid)
   FROM pg_stat_activity
   WHERE datname = :'app_db' AND usename = :'app_role'
     AND backend_start <= :'fence_time'::timestamptz AND state = 'idle';

   SELECT count(*) AS connections_opened_before_fence
   FROM pg_stat_activity
   WHERE datname = :'app_db' AND usename = :'app_role'
     AND backend_start <= :'fence_time'::timestamptz;
   ```

   Repeat the final two queries until the count reaches zero, using the same saved `fence_time`. Let active transactions finish. If the count persists past the time limit or readiness fails, keep the guest isolated and stop PeerTube. Preserve the original error and the observed role/queue state.

5. In a **new application-role connection**, recheck the read-only setting. Probe a zero-row write in an explicit transaction and verify PostgreSQL reports SQLSTATE `25006`. Check a local API GET for 200, a known local asset byte range for 206, nginx's write refusal and the paused queues. Confirm the instance still has its expected database, artwork and identity. A local range proves only the specific asset retrieved. Validate media served by the external bucket through its independent recovery procedure.

## Finish the drill

Record database, artwork, cold-start and external dependency results separately. For a disposable guest, verify its identity before requesting destruction. Wait for the provider's destroy action to complete **and** VPC membership to clear before removing its firewall, dedicated VPC or unused tag. Recheck the retained image, both live resources and authoritative DNS.

Keep the old production server available through the agreed rollback hold, the first scheduled independent offsite backup verification, and resolution of outstanding incidents. A real return to the old origin also needs a plan for writes accepted by Vidra and an explicit decision to move traffic. Release the network and worker fences only for that coordinated operation.
