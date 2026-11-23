# Source-metadata ingestion and per-session ordering

Software increment, November 23, 2026. The repository now includes compatible
storage for the producer metadata, idempotent receipt handling and per-session
query views. It has not been deployed to the mini PC. Existing Grafana queries
remain arrival-based; LAN time configuration, active-session selection and the
final dashboard switch are still pending. This is not full end-to-end acceptance.

## Stored clocks and provenance

Migration `ground-station/migrations/002-source-metadata.sql` runs after 001.
It preserves existing rows and keeps `telemetry_data.time` as the broker-arrival
partition key. It adds:

- `broker_arrival_ms`: explicit broker arrival value from the action.
- `received_at`: database insertion time; historical rows remain NULL rather than
  receiving a fabricated migration-time receipt. This is a database wall clock,
  not a source measurement clock or ordering guarantee.
- Raw source version/session/sequence/time/age fields from the producer.
- `source_identity_valid`: validation of the supported identity format, not
  authentication of a physical board.
- `source_event_time`: nullable qualified frame-assembly time. It is not the ADC
  acquisition time or proof of external UTC accuracy.
- `time_provenance`: explicit interpretation of the available time metadata.

Provenance values are `legacy-arrival`, `unsupported-source`,
`invalid-source-identity`, `source-unsynchronized`, `invalid-source-time`, and
`source-kernel-reference-unknown`. A source event time is derived only for a
supported identity, valid UNIX flag, supported quality 1 and integer epoch
milliseconds within the explicit export range through year 9999. Other values
remain stored without an invented 1970 timestamp or calibrated UTC claim.

Unsigned 64-bit values use unscaled PostgreSQL NUMERIC, not signed BIGINT or
floating point. Integer range is validated without rounding fractions. Equivalent
integer forms such as 1 and 1.0 are normalized for fingerprint stability. EMQX
renders these values as decimal strings; the action binds TEXT then casts to
NUMERIC, preserving exactness through a standard text parameter boundary.

The protobuf rule accepts the versioned producer fields. The legacy flight JSON
rule deliberately supplies metadata version 0; it does not reinterpret arbitrary
JSON payload fields as this fill-station contract. Older protobuf producers also
remain version 0. Unknown versions, unsupported units and malformed identities
remain inspectable with arrival-time semantics and are not silently deduplicated
using a guessed identity.

## Duplicate handling and transaction boundaries

A private ordinary PostgreSQL table, `ground_telemetry_private.source_receipts`,
has a primary key on unit/session-high/session-low/sequence. This avoids requiring
a unique index without the arrival partition key on the Timescale hypertable.
The ledger and telemetry row participate in the same insertion transaction:

- A new valid identity reserves a receipt and inserts its history row.
- An exact repeat is suppressed, even with another arrival/receipt timestamp or
  arrival partition. The original history row is retained.
- A known-v1 payload conflict for the same identity raises SQLSTATE 23505; it does
  not overwrite the original observation.
- A later row/transaction failure rolls the receipt back, allowing a valid retry.

The trigger fingerprints a frozen list of v1 protobuf fields with SHA-256 after
the existing availability normalization. Arrival/receipt times and later table
columns are excluded. Do not change that v1 fingerprint inventory casually: future
schema/protocol additions require an explicit compatibility review. This is
idempotent ingestion of received frames, not a guarantee that QoS-0 MQTT delivered
all frames or cryptographic authentication of their sender.

The trigger uses SECURITY DEFINER with a fixed search path and schema-qualified
private access. The ingestion account retains INSERT-only access to telemetry;
it cannot read/delete receipts or update history. Readers get SELECT on the two
new views. The action explicitly sets `resource_opts.batch_size=1` so a conflicting
frame does not roll unrelated frames back in a connector batch. A caller's own
manual multi-row transaction still has normal PostgreSQL atomicity.

There is no automatic ledger pruning. At 10 source frames/second, one day can add
864,000 receipts in addition to telemetry history. Measure disk use and coordinate
receipt/history retention before adding automatic cleanup. Deleting receipts can
permit delayed retries to be inserted again; deleting history does not itself
remove receipts. No broad GC or deletion is performed by this migration.

## Query views and their limits

`telemetry_latest_in_session` returns the greatest sequence per valid session.
A delayed lower sequence cannot replace that session's head, even after a wall
clock step. It deliberately returns separate rows for separate sessions: random
session IDs, sequence numbers reset at restart, and first/last arrival time do
not establish a guaranteed global order across restarts. Active-session selection
must be explicit in the later application integration.

`telemetry_event_history` adds `display_time`, choosing qualified source time when
available and arrival time otherwise, with provenance retained. This does not
turn an unknown source time into a source measurement. No existing dashboard query
is automatically redirected to either view.

For an explicitly selected real session, inspect history with a query shaped as:

```sql
SELECT publisher_sequence::text, source_monotonic_ms::text,
       source_event_time, time AS broker_time, time_provenance, pt_1_pressure
FROM telemetry_data
WHERE unit_id = 0 AND source_identity_valid
  AND publisher_session_hi = 123::numeric
  AND publisher_session_lo = 456::numeric
ORDER BY publisher_sequence;
```

Replace 123/456 with the actual session; these are examples. Preserve identifiers
and sequence as exact text at browser/JSON boundaries. Do not compare full uint64
values through JavaScript Number, pick MAX(random session ID) as the active board,
or reconstruct exact sample UTC across clock steps from age alone.

## Provisioning and eventual rollout

The immutable package and runtime asset builder include migration 002. Database
provisioning applies the base schema, 001, 002 and role grants before reconciling
the broker's schema/rules/action. Old rows are not rewritten or assigned inferred
source sessions. Repeated provisioning retains rows/receipts and normalizes no
historical source metadata retroactively.

When the combined candidate is frozen, apply it in the maintenance session:

1. Run database migrations and view grants before installing the new SQL action.
   Existing statement/lock deadlines remain. Index creation on existing history
   can require time; a failed migration must be investigated rather than bypassed.
2. Install the matching protobuf registry schema, both rules, and shared action.
   Verify old producers continue storing version-0 rows and connector health.
3. Deploy the producer image when ready. Verify exact session/sequence strings,
   provenance, sample validity/age, duplicate suppression and per-session heads.
4. Exercise restart, shuffled/duplicate traffic and outages with a synthetic test
   producer before accepting real operation. Confirm camera/UI/recording continuity.
5. Add LAN time and explicit active-session selection, then switch reviewed
   time/latest-value queries while retaining the accepted dashboard appearance.

An older producer/action can continue using the additive table with legacy
arrival semantics. Retain the schema and receipt state during a reviewed rollback;
do not drop telemetry or receipt tables to silence a migration/integration error.
Building this repository or running the host tests applies nothing to the real PC.

## Verification completed and pending

34 source-ingestion checks passed on a disposable PostgreSQL 17.11 installation:
ordinary tables and actual PostgreSQL time partitions; migration repetition and
old rows; shuffled history and sequence heads; concurrent retries; conflicting
payloads; rollback; full uint64/text-prepared binding; equivalent integer forms;
future columns; invalid/unknown clocks; and least-privilege account behavior.
Four existing availability/PostgreSQL tests and 24 runtime/provisioning checks
also passed. The actual Nix-filtered source is checked in isolation for missing
assets. Tests use private Unix sockets and remove their clusters afterwards.
No Docker or operational database is contacted.

To repeat the database suite with your own PostgreSQL 17 binaries:

```sh
PG_BIN=/absolute/path/to/postgresql-17/bin \
  python3 -m unittest discover -s tests -p test_source_ingestion.py
```

The real Timescale extension, live EMQX rule/driver behavior, Linux package/system
build, deployed migration, dashboard integration and hardware remain pending.
PostgreSQL partition tests and source inspection do not substitute for those.

Design references: [Timescale unique-index partition requirements](https://github.com/timescale/docs/blob/latest/use-timescale/hypertables/hypertables-and-unique-indexes.md),
[PostgreSQL trigger behavior](https://www.postgresql.org/docs/17/trigger-definition.html),
[SECURITY DEFINER search-path guidance](https://www.postgresql.org/docs/17/sql-createfunction.html),
and [EMQX built-in conversions](https://docs.emqx.com/en/cloud/latest/data_integration/rule-sql-builtin-functions.html).

## Explicit session query interface (migration 003)

The candidate now packages and applies migration 003 after 002 and before role
grants. It adds a read-only session catalog and selected-session functions. This
is the shared database interface for later consumers; the current Grafana and
Commanding pages have not been switched to it. No global active session is guessed
or persisted by this migration.

```sql
SELECT unit_id, session_id, publisher_session_hi::text,
       publisher_session_lo::text, last_sequence::text,
       stored_frames, first_received_at, last_received_at
FROM telemetry_sessions;

-- Replace both example halves with an observed session belonging to this run.
SELECT publisher_sequence::text, pt_1_pressure, source_event_time, time_provenance
FROM telemetry_session_head(0, 123::numeric, 456::numeric);

SELECT publisher_sequence::text, display_time, time_provenance, pt_1_pressure
FROM telemetry_session_history(0, 123::numeric, 456::numeric, 0::numeric, 100)
ORDER BY publisher_sequence;
```

The head is the greatest sequence within exactly that session. History returns
ascending sequence, exclusively after the cursor, at most 1,000 rows (default
100); use the last returned sequence as the next cursor. An outer SQL query must
specify its own ORDER BY when it requires guaranteed row order. Cursor paging is
not a snapshot: late lower-sequence inserts can fall behind an already consumed
cursor. Use overlapping rereads or a fixed snapshot for archival completeness;
this API is not a lossless streaming subscription or export protocol.

The 32-character session_id is an exact lowercase hexadecimal rendering of both
uint64 halves, including leading zeros. IDs/cursors must remain NUMERIC or text,
never JavaScript Number. Neither random ID ordering nor last_received_at proves
which boot is active: old sessions can receive delayed data. The catalog receipt
bounds describe storage activity, not boot times or sensor sample times.

Only known-valid v1 fill-station sessions are selectable. Invalid/null/fractional
or out-of-range IDs/cursors, all-zero IDs, unsupported unit IDs and invalid page
sizes fail with SQLSTATE 22023. Unknown but valid IDs return no rows; they never
fall back to another session or legacy data. Legacy/unknown data remain available
through telemetry_data and telemetry_event_history. Current function return row
types track their underlying relations; future schema changes need compatibility
review. Functions run with caller privileges and a fixed search path; only the
reader role receives execution permission, not the ingest role or PUBLIC.

Host acceptance covers ordinary PostgreSQL and PostgreSQL time partitions,
including delayed lower sequences, interleaved sessions, backward source/arrival
clocks, exact maximum uint64 identity, invalid requests, repeated migration and
reader/ingest/unrelated-role permissions. Actual Timescale plans/performance,
service rollout, explicit operator selection and consumer wiring remain pending.


The generated Grafana consumer now uses explicit session selection for its six
fill panels. See [operator behavior and acceptance](grafana-sessions.md). The
source export remains unchanged; historical notes above about consumers pending
refer to the earlier block. Real browser acceptance and source-time charts remain
pending; Commanding is not changed.
