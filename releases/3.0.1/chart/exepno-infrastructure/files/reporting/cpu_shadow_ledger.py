"""Local shadow-meter ledger. No network, pricing or billing submission.

One owner per local database path. Not a distributed Kubernetes lock.
Input timestamps are epoch milliseconds supplied by the collector.
CPU requests are supplied as decimal core strings, e.g. "3.050".
"""

import fcntl
import json
import sqlite3
import uuid
from decimal import Decimal, localcontext
from pathlib import Path


def nanocpus(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("CPU must be a bounded decimal string.")

    number = Decimal(value)

    if not number.is_finite() or number < 0 or number > 1_000_000:
        raise ValueError("Invalid CPU quantity.")

    scaled = number * Decimal(1_000_000_000)

    if scaled != scaled.to_integral_value():
        raise ValueError("CPU precision exceeds nine decimal places.")

    return int(scaled)


class ShadowLedger:
    def __init__(self, filename, scope, max_gap_ms=60_000):
        if (
            not isinstance(scope, str)
            or not scope
            or len(scope) > 1000
            or not isinstance(max_gap_ms, int)
            or isinstance(max_gap_ms, bool)
            or not 1000 <= max_gap_ms <= 3_600_000
        ):
            raise ValueError("Invalid ledger configuration.")

        self.path = Path(filename).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

        self.owner = str(uuid.uuid4())
        self.max_gap_ms = max_gap_ms
        self.db = None
        self.lock = None

        try:
            self.lock = open(str(self.path) + ".lock", "a+b")
            self.path.with_name(self.path.name + ".lock").chmod(0o600)

            try:
                fcntl.flock(
                    self.lock.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )
            except BlockingIOError:
                raise RuntimeError("Another local collector owns this ledger.")

            self.db = sqlite3.connect(
                str(self.path),
                isolation_level=None,
                timeout=5,
            )
            self.path.chmod(0o600)

            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA foreign_keys=ON")

            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    configuration TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS samples (
                    timestamp_ms INTEGER PRIMARY KEY,
                    nano_cpu TEXT NOT NULL,
                    topology TEXT NOT NULL,
                    owner TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS intervals (
                    start_ms INTEGER PRIMARY KEY,
                    end_ms INTEGER NOT NULL UNIQUE,
                    kind TEXT NOT NULL CHECK (
                        kind IN (
                            'estimated',
                            'restart_gap',
                            'sampling_gap',
                            'configuration_change'
                        )
                    ),
                    nano_cpu_ms TEXT,
                    CHECK (end_ms > start_ms),
                    FOREIGN KEY(start_ms) REFERENCES samples(timestamp_ms),
                    FOREIGN KEY(end_ms) REFERENCES samples(timestamp_ms)
                );
            """)

            configuration = json.dumps(
                {
                    "schemaVersion": 1,
                    "scope": scope,
                    "maxGapMs": max_gap_ms,
                    "mode": "shadow_only",
                },
                sort_keys=True,
            )

            self.db.execute(
                "INSERT OR IGNORE INTO metadata VALUES (1, ?)",
                (configuration,),
            )

            saved = self.db.execute(
                "SELECT configuration FROM metadata WHERE id = 1"
            ).fetchone()[0]

            if saved != configuration:
                raise RuntimeError(
                    "Ledger scope or configuration differs. Do not reuse it."
                )

        except Exception:
            self.close()
            raise

    def observe(self, timestamp_ms, cpu_cores, topology):
        if (
            not isinstance(timestamp_ms, int)
            or isinstance(timestamp_ms, bool)
            or not 0 <= timestamp_ms <= 9_000_000_000_000_000
            or not isinstance(topology, str)
            or not topology
            or len(topology) > 4096
        ):
            raise ValueError("Invalid observation.")

        amount = str(nanocpus(cpu_cores))
        self.db.execute("BEGIN IMMEDIATE")

        try:
            existing = self.db.execute(
                "SELECT nano_cpu, topology FROM samples WHERE timestamp_ms = ?",
                (timestamp_ms,),
            ).fetchone()

            if existing:
                if existing != (amount, topology):
                    raise RuntimeError("Conflicting replay of an observation.")

                self.db.execute("COMMIT")
                return "duplicate"

            previous = self.db.execute("""
                SELECT timestamp_ms, nano_cpu, topology, owner
                FROM samples ORDER BY timestamp_ms DESC LIMIT 1
                """).fetchone()

            if previous and timestamp_ms <= previous[0]:
                raise RuntimeError(
                    "Observation clock moved backward. No interval recorded."
                )

            self.db.execute(
                "INSERT INTO samples VALUES (?, ?, ?, ?)",
                (timestamp_ms, amount, topology, self.owner),
            )

            outcome = "baseline"

            if previous:
                start, previous_cpu, previous_topology, previous_owner = previous
                elapsed = timestamp_ms - start

                if previous_owner != self.owner:
                    outcome = "restart_gap"
                elif elapsed > self.max_gap_ms:
                    outcome = "sampling_gap"
                elif previous_cpu != amount or previous_topology != topology:
                    outcome = "configuration_change"
                else:
                    outcome = "estimated"

                # No usage is invented across restart, outage or transition gaps.
                measured = (
                    str(int(previous_cpu) * elapsed) if outcome == "estimated" else None
                )

                self.db.execute(
                    "INSERT INTO intervals VALUES (?, ?, ?, ?)",
                    (start, timestamp_ms, outcome, measured),
                )

            self.db.execute("COMMIT")
            return outcome

        except Exception:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def summary(self):
        rows = self.db.execute(
            "SELECT kind, nano_cpu_ms FROM intervals ORDER BY start_ms"
        ).fetchall()

        totals = {}
        exact = 0

        for kind, value in rows:
            totals[kind] = totals.get(kind, 0) + 1
            if kind == "estimated":
                exact += int(value)

        with localcontext() as context:
            context.prec = 40
            hours = Decimal(exact) / Decimal(3_600_000_000_000_000)

        return {
            "mode": "shadow_only",
            "samples": self.db.execute("SELECT COUNT(*) FROM samples").fetchone()[0],
            "intervalsByKind": totals,
            "estimatedNanoCpuMilliseconds": str(exact),
            "estimatedCpuHours": str(hours),
            "googleUsageSubmitted": False,
            "commercialContractConfirmed": False,
        }

    def close(self):
        if self.db is not None:
            try:
                self.db.close()
            finally:
                self.db = None

        if self.lock is not None:
            try:
                fcntl.flock(self.lock.fileno(), fcntl.LOCK_UN)
            finally:
                self.lock.close()
                self.lock = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
