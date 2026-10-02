"""Connected commercial-reporting runtime.

Not invoked by default. Real reporting requires explicit deployment
authorization, the declared measurement definition and Marketplace credentials.

Reuses the tested exact ledger/outbox. Their synthetic envelope is internal
only; the outbound report uses the approved metric and no test label.
"""

import hashlib
import json
import os
import signal
import sys
import time
import urllib.request
from pathlib import Path

from commercial_contract import installation_binding, bind_state
from prepare_agent_config import (
    read_reporting_secret,
    prepare_configuration,
    require_tmpfs,
)
from cpu_shadow_ledger import ShadowLedger
from ubb_shadow_outbox import ShadowOutbox
from cpu_seconds_adapter import cpu_seconds, METRIC
from kubernetes_disk_collector import snapshot, stamp, NoRedirect

STATE = Path("/billing-state")
CONFIG = Path("/run/exepno-agent-config")
SECRET = Path("/run/exepno-reporting-secret")

DEFINITION = "requested_cpu_running_regular_containers_v1"
MAX_SAMPLES = 120
MAX_REPORTS = 120
INTERVAL = 30
STOP = False


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def configuration():
    require(
        os.environ.get("EXEPNO_COMMERCIAL_REPORTING_AUTHORIZED") == "true",
        "Commercial reporting has not been authorized.",
    )
    require(
        os.environ.get("EXEPNO_CPU_MEASUREMENT_DEFINITION") == DEFINITION,
        "Unsupported CPU measurement definition.",
    )

    scope = {
        "projectId": os.environ["EXEPNO_CUSTOMER_PROJECT"],
        "namespace": os.environ["EXEPNO_NAMESPACE"],
        "instance": os.environ["EXEPNO_INSTANCE"],
        "applicationUid": os.environ["EXEPNO_APPLICATION_UID"],
    }

    require(all(scope.values()), "Installation identity is incomplete.")
    require(bool(os.environ.get("EXEPNO_AGENT_IMAGE")), "Agent image missing.")

    return scope


def atomic_json(file, data):
    temporary = file.with_name(file.name + ".pending")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(data, handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, file)

    descriptor = os.open(str(file.parent), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def initialize():
    scope = configuration()
    require_tmpfs(CONFIG)

    # Inspect the old state before generating any private configuration.
    binding_exists = (STATE / "binding.json").exists()
    paired = STATE / "paired-state.json"
    started = STATE / "sender/started.json"

    if binding_exists:
        require(
            paired.is_file(), "Incomplete state initialization requires inspection."
        )

        record = json.loads(paired.read_text())
        require(
            record
            == {
                "version": 1,
                "agentImage": os.environ["EXEPNO_AGENT_IMAGE"],
                "definition": DEFINITION,
            },
            "Agent or measurement definition changed; review migration first.",
        )

        for name in ("sender", "agent"):
            directory = STATE / name
            require(
                directory.is_dir() and not directory.is_symlink(),
                "Paired state directory missing.",
            )

        if started.exists():
            for name in ("ledger.sqlite", "outbox.sqlite"):
                require(
                    (STATE / "sender" / name).is_file(),
                    "Previously initialized sender state is missing.",
                )
        else:
            require(
                not list((STATE / "sender").iterdir()),
                "Uncertain sender initialization requires inspection.",
            )
    else:
        # bind_state will reject any pre-existing ledger/agent/test contents.
        require(not paired.exists(), "State binding missing.")

    result = prepare_configuration(
        SECRET, STATE, CONFIG, scope, DEFINITION, authorized=True
    )

    if not binding_exists:
        (STATE / "sender").mkdir(mode=0o700)
        (STATE / "agent").mkdir(mode=0o700)
        atomic_json(
            paired,
            {
                "version": 1,
                "agentImage": os.environ["EXEPNO_AGENT_IMAGE"],
                "definition": DEFINITION,
            },
        )

    print(
        json.dumps(
            {
                "configurationWritten": result["configurationWritten"],
                "bindingSha256": result["bindingSha256"],
                "agentStarted": False,
                "usageSubmitted": False,
            }
        ),
        flush=True,
    )


def status():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open("http://127.0.0.1:3456/status", timeout=5) as response:
        raw = response.read(65537)
        require(len(raw) <= 65536, "Unexpected status-response size.")
        value = json.loads(raw)

    require(
        isinstance(value, dict)
        and isinstance(value.get("currentFailureCount"), int)
        and isinstance(value.get("totalFailureCount"), int),
        "Agent status contract mismatch.",
    )
    require(
        value["currentFailureCount"] == 0 and value["totalFailureCount"] == 0,
        "Agent reports delivery failure; operator inspection required.",
    )
    return value


def wire_payload(payload):
    # The tested outbox validates the internal exact-integer envelope.
    internal = json.loads(payload)
    require(
        internal["name"] == "exepno_test_nanocpu_milliseconds"
        and internal["labels"] == {"test": "disk-only"},
        "Unexpected internal measurement envelope.",
    )

    return json.dumps(
        {
            "name": METRIC,
            "startTime": internal["startTime"],
            "endTime": internal["endTime"],
            "value": {
                "doubleValue": cpu_seconds(internal["value"]["int64Value"]),
            },
            "labels": {},
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def send_once(payload):
    # No redirect or retry. Outbox marks uncertain outcomes for inspection.
    request = urllib.request.Request(
        "http://127.0.0.1:3456/report",
        data=wire_payload(payload),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=10) as response:
        response.read(4097)
        return response.status


def collect():
    scope = configuration()

    # Collector does not mount the reporting Secret or private agent config.
    binding_file = STATE / "binding.json"
    require(binding_file.is_file(), "Installation binding missing.")
    binding = json.loads(binding_file.read_text())

    require(
        binding.get("installation") == scope
        and binding.get("measurementDefinition") == DEFINITION
        and binding.get("metric") == METRIC
        and binding.get("destination") == "google_service_control",
        "Persistent reporting identity mismatch.",
    )

    binding_hash = hashlib.sha256(binding_file.read_bytes()).hexdigest()
    destination = "servicecontrol:" + binding_hash

    deadline = time.monotonic() + 120
    while not STOP:
        try:
            status()
            break
        except Exception:
            require(time.monotonic() < deadline, "Agent startup/status failed.")
            time.sleep(2)

    if STOP:
        return

    sender = STATE / "sender"
    require(sender.is_dir(), "Sender directory missing.")
    started = sender / "started.json"

    with ShadowLedger(
        sender / "ledger.sqlite", destination, max_gap_ms=45000
    ) as ledger, ShadowOutbox(
        sender / "outbox.sqlite", destination, destination
    ) as outbox:
        if not started.exists():
            atomic_json(started, {"initialized": True})

        def drain():
            status()

            rows = ledger.db.execute("""
                SELECT start_ms,end_ms,nano_cpu_ms
                FROM intervals WHERE kind='estimated' ORDER BY start_ms
            """).fetchall()
            require(len(rows) <= MAX_REPORTS, "Controlled-test report budget reached.")

            for first, last, amount in rows:
                outbox.enqueue(
                    {
                        "name": "exepno_test_nanocpu_milliseconds",
                        "startTime": stamp(first),
                        "endTime": stamp(last),
                        "value": {"int64Value": int(amount)},
                        "labels": {"test": "disk-only"},
                    }
                )

            while not STOP:
                status()
                if outbox.send_next(send_once) is None:
                    break

        # Existing uncertain reports block sending through the tested outbox.
        drain()

        epoch = time.time_ns() // 1_000_000
        monotonic = time.monotonic_ns()

        while not STOP:
            count = ledger.db.execute("SELECT COUNT(*) FROM samples").fetchone()[0]

            if count >= MAX_SAMPLES:
                print(
                    "CONTROLLED TEST BUDGET COMPLETE. Further sampling stopped.",
                    flush=True,
                )
                while not STOP:
                    time.sleep(2)
                break

            begun = time.monotonic()
            cores, topology = snapshot(scope)
            require(time.monotonic() - begun <= 15, "Slow sample rejected.")

            timestamp = epoch + (time.monotonic_ns() - monotonic) // 1_000_000
            require(
                abs(timestamp - time.time_ns() // 1_000_000) <= 5000,
                "Clock adjustment requires inspection.",
            )

            outcome = ledger.observe(timestamp, cores, topology)
            drain()
            health = status()

            print(
                json.dumps(
                    {
                        "mode": "servicecontrol",
                        "sample": count + 1,
                        "cpuRequests": cores,
                        "interval": outcome,
                        "senderStates": outbox.summary()["states"],
                        "agentLastReportSuccess": health.get("lastReportSuccess"),
                        "perReportGoogleAcceptanceConfirmed": False,
                    }
                ),
                flush=True,
            )

            until = time.monotonic() + INTERVAL
            while not STOP and time.monotonic() < until:
                time.sleep(1)


def stop(*_):
    global STOP
    STOP = True


if __name__ == "__main__":
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    try:
        if sys.argv[1:] == ["init"]:
            initialize()
        elif not sys.argv[1:]:
            collect()
        else:
            raise RuntimeError("Unknown operation.")
    except Exception:
        print(
            "COMMERCIAL METER HALTED: preserve state and inspect. "
            "Do not reset receipts or resend uncertain reports.",
            flush=True,
        )
        raise SystemExit(1)
