# Live pgbot PostgreSQL lab

This lab creates a real PostgreSQL lock-contention incident while preserving enough database capacity for the diagnostic instrument itself.

The `contention` container opens one transaction that locks a row and three identical waiter queries that block on the same row. The workflow waits until PostgreSQL reports those sessions with `wait_event_type = 'Lock'`, then runs the pinned pgbot release through a read-only `pg_monitor` role.

The lab deliberately does not prove connection saturation. An earlier version exhausted connection slots so aggressively that some pgbot collectors correctly became `unavailable`. That is a useful evidence-quality lesson: a diagnostic source must retain enough operational headroom to observe the failure it is meant to describe.

After pgbot captures the live lock finding, the workload is removed and `scripts/live_postgresql_trace.py` runs a real delayed PostgreSQL client query. Its measured timestamps are translated through the existing OpenTelemetry adapter and composed with the pgbot evidence in one Causcope semantic scope.
