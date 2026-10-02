"""Durable sender boundary for the UBB disk-only experiment.

Single-host SQLite + file lock.
No automatic retry of accepted or uncertain submissions.
Not distributed leader election or an exactly-once billing implementation.
"""

import fcntl
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

TEST_METRIC = "exepno_test_nanocpu_milliseconds"


def normalize_report(report):
    required = {"name", "startTime", "endTime", "value", "labels"}

    if not isinstance(report, dict) or set(report) != required:
        raise ValueError("Unexpected report fields.")

    if (
        report["name"] != TEST_METRIC
        or report["labels"] != {"test": "disk-only"}
        or not isinstance(report["value"], dict)
        or set(report["value"]) != {"int64Value"}
    ):
        raise ValueError("Only the synthetic disk-test metric is permitted.")

    amount = report["value"]["int64Value"]
    if (
        not isinstance(amount, int)
        or isinstance(amount, bool)
        or not 0 <= amount <= 2**63 - 1
    ):
        raise ValueError("Invalid integer quantity.")

    def timestamp(value):
        if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
            r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})",
            value,
        ):
            raise ValueError("Invalid timestamp precision or timezone.")

        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        parsed = parsed.astimezone(timezone.utc)
        delta = parsed - datetime(1970, 1, 1, tzinfo=timezone.utc)
        micros = (
            delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds
        )
        formatted = parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")
        return micros, formatted

    start, start_text = timestamp(report["startTime"])
    end, end_text = timestamp(report["endTime"])

    if end <= start:
        raise ValueError("Invalid interval.")

    canonical = json.dumps(
        {
            "name": TEST_METRIC,
            "startTime": start_text,
            "endTime": end_text,
            "value": {"int64Value": amount},
            "labels": {"test": "disk-only"},
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    identity = hashlib.sha256(canonical.encode()).hexdigest()
    return identity, start, end, canonical


class ShadowOutbox:
    def __init__(self, filename, installation, destination):
        # Destination identifies the particular agent experiment/configuration.
        # Never reuse this database for another destination.
        if any(
            not isinstance(value, str) or not value or len(value) > 1000
            for value in (installation, destination)
        ):
            raise ValueError("Explicit installation and destination required.")

        supplied = Path(filename).expanduser()
        if supplied.is_symlink():
            raise RuntimeError("Refusing a symlinked database.")

        self.path = supplied.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = None
        self.lock = None

        lock_path = Path(str(self.path) + ".lock")
        if lock_path.is_symlink():
            raise RuntimeError("Refusing a symlinked lock.")

        try:
            self.lock = lock_path.open("a+b")
            lock_path.chmod(0o600)
            try:
                fcntl.flock(
                    self.lock.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )
            except BlockingIOError:
                raise RuntimeError("Another local sender owns this outbox.")

            self.db = sqlite3.connect(str(self.path), isolation_level=None, timeout=5)
            self.path.chmod(0o600)
            self.db.execute("PRAGMA synchronous=FULL")

            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    configuration TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY,
                    start_us INTEGER NOT NULL,
                    end_us INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(
                        state IN (
                            'pending', 'sending',
                            'accepted', 'needs_inspection'
                        )
                    ),
                    http_status INTEGER,
                    UNIQUE(start_us, end_us),
                    CHECK(end_us > start_us)
                );
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)

            configuration = json.dumps(
                {
                    "schema": 1,
                    "mode": "disk_only",
                    "installation": installation,
                    "destination": destination,
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
                raise RuntimeError("Outbox installation/destination mismatch.")

            # A crash may have happened before sending, during sending, or
            # after HTTP acceptance. We cannot safely infer which.
            self.db.execute("BEGIN IMMEDIATE")
            try:
                interrupted = self.db.execute(
                    "SELECT id FROM reports WHERE state = 'sending'"
                ).fetchall()

                for (identity,) in interrupted:
                    self.db.execute(
                        "UPDATE reports SET state='needs_inspection' WHERE id=?",
                        (identity,),
                    )
                    self.db.execute(
                        "INSERT INTO events(report_id,state,reason) VALUES(?,?,?)",
                        (identity, "needs_inspection", "sender_restart"),
                    )
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

        except BaseException:
            self.close()
            raise

    def enqueue(self, report):
        identity, start, end, payload = normalize_report(report)
        self.db.execute("BEGIN IMMEDIATE")

        try:
            existing = self.db.execute(
                "SELECT payload FROM reports WHERE id=?", (identity,)
            ).fetchone()

            if existing:
                if existing[0] != payload:
                    raise RuntimeError("Report identity conflict.")
                self.db.execute("COMMIT")
                return identity

            overlap = self.db.execute(
                """
                SELECT id FROM reports
                WHERE start_us < ? AND end_us > ?
                LIMIT 1
                """,
                (end, start),
            ).fetchone()

            if overlap:
                raise RuntimeError("Conflicting or overlapping interval.")

            self.db.execute(
                """
                INSERT INTO reports(id,start_us,end_us,payload,state)
                VALUES(?,?,?,?, 'pending')
                """,
                (identity, start, end, payload),
            )
            self.db.execute(
                "INSERT INTO events(report_id,state,reason) VALUES(?,?,?)",
                (identity, "pending", "enqueued"),
            )
            self.db.execute("COMMIT")
            return identity

        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def transition(self, identity, expected, target, reason, status=None):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            changed = self.db.execute(
                """
                UPDATE reports SET state=?, http_status=?
                WHERE id=? AND state=?
                """,
                (target, status, identity, expected),
            )
            if changed.rowcount != 1:
                raise RuntimeError("Unexpected outbox transition.")

            self.db.execute(
                "INSERT INTO events(report_id,state,reason) VALUES(?,?,?)",
                (identity, target, reason),
            )
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def send_next(self, sender):
        """sender receives JSON bytes and returns an HTTP status.

        The sender MUST make exactly one attempt: no redirect/retry policy.
        """
        if self.db.execute(
            "SELECT 1 FROM reports WHERE state IN ('sending','needs_inspection')"
        ).fetchone():
            raise RuntimeError(
                "Uncertain delivery exists. Inspect; automatic sending is blocked."
            )

        row = self.db.execute("""
            SELECT id,payload FROM reports
            WHERE state='pending' ORDER BY start_us LIMIT 1
            """).fetchone()

        if not row:
            return None

        identity, payload = row

        # Durable reservation BEFORE the external operation.
        self.transition(identity, "pending", "sending", "send_attempt_reserved")

        try:
            status = sender(payload.encode("utf-8"))

            if not isinstance(status, int) or isinstance(status, bool) or status != 200:
                raise RuntimeError("Agent acceptance was not confirmed.")

        except BaseException:
            # If this checkpoint itself fails, the durable 'sending' state
            # is converted to needs_inspection when reopened.
            self.transition(
                identity,
                "sending",
                "needs_inspection",
                "http_outcome_not_confirmed",
            )
            raise

        # If commit fails after HTTP 200, DO NOT retry the HTTP request.
        self.transition(
            identity,
            "sending",
            "accepted",
            "http_200_received_not_downstream_delivery",
            status,
        )
        return identity

    def summary(self):
        return {
            "mode": "disk_only",
            "states": dict(
                self.db.execute(
                    "SELECT state,COUNT(*) FROM reports GROUP BY state"
                ).fetchall()
            ),
            "downstreamDeliveryConfirmed": False,
            "googleBillingEnabled": False,
        }

    def close(self):
        if self.db is not None:
            self.db.close()
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
