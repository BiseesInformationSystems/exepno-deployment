"""Bounded Kubernetes integration collector. DISK REPORTING ONLY.

Uses the tested ledger, outbox and CPU-seconds adapter.
No Service Control credentials or live billing configuration.

Requires a dedicated persistent volume. Missing or inconsistent state
requires inspection; this process never deletes or repairs records.
"""

import hashlib
import json
import os
import re
import signal
import ssl
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from cpu_shadow_ledger import ShadowLedger, nanocpus
from ubb_shadow_outbox import ShadowOutbox
from cpu_seconds_adapter import METRIC, seconds_report, seconds_payload

ROOT = Path("/data")
TOKEN = Path("/var/run/exepno-api/token")
CA = "/var/run/exepno-api/ca.crt"

COMPONENTS = {
    "frontend",
    "python-backend",
    "gateway",
    "mongodb",
    "minio",
    "qdrant",
}

MAX_SAMPLES = 120
INTERVAL_SECONDS = 30
MAX_GAP_MS = 45_000
STOP = False


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def configuration():
    require(
        os.environ.get("EXEPNO_REPORTING_MODE") == "disk_only",
        "Only disk-only operation is implemented.",
    )
    instance = os.environ["EXEPNO_INSTANCE"]
    namespace = os.environ["EXEPNO_NAMESPACE"]

    for value in (instance, namespace):
        require(
            re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", value) is not None,
            "Invalid installation identity.",
        )

    return {
        "version": 1,
        "mode": "disk_only",
        "instance": instance,
        "namespace": namespace,
        "agentImage": os.environ["EXEPNO_AGENT_IMAGE"],
        "definition": "requested_running_regular_container_cpu_time_v1",
        "maxSamples": MAX_SAMPLES,
    }


def durable_json(file, value):
    # Used only for small setup markers, never credential values.
    temporary = file.with_name(file.name + ".pending")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True)
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
    config = configuration()
    marker = ROOT / "installation.json"
    directories = ("sender", "agent", "reports")

    if marker.exists():
        require(
            json.loads(marker.read_text()) == config,
            "Reporting configuration/state identity changed.",
        )
        for name in directories:
            require((ROOT / name).is_dir(), "Paired state directory missing.")

        sender = ROOT / "sender"
        if (sender / "started.json").exists():
            for name in ("ledger.sqlite", "outbox.sqlite"):
                require((sender / name).is_file(), "Sender state was lost.")
        else:
            require(
                not list(sender.iterdir()),
                "Incomplete initial state. Inspect instead of recreating.",
            )
    else:
        require(
            not [item for item in ROOT.iterdir() if item.name != "lost+found"],
            "Nonempty volume has no reporting identity marker.",
        )
        for name in directories:
            (ROOT / name).mkdir(mode=0o700)
        durable_json(marker, config)

    print("PASS: reporting volume identity and paired directories.", flush=True)


def fetch_json(url, headers=None, timeout=10, tls=False):
    handlers = [urllib.request.ProxyHandler({}), NoRedirect()]
    if tls:
        handlers.append(
            urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=CA))
        )

    opener = urllib.request.build_opener(*handlers)
    request = urllib.request.Request(url, headers=headers or {})

    with opener.open(request, timeout=timeout) as response:
        data = response.read(8_000_001)
        require(len(data) <= 8_000_000, "Response exceeded inspection bound.")
        return json.loads(data)


def owner_uid(resource, kind):
    matches = [
        item["uid"]
        for item in resource.get("metadata", {}).get("ownerReferences", [])
        if item.get("kind") == kind and item.get("controller") is True
    ]
    return matches[0] if len(matches) == 1 else None


def kubernetes_nanocpus(value):
    """Convert supported Kubernetes CPU quantities to exact nanocpus.

    The ledger's decimal-core input contract remains unchanged.
    Unsupported, missing or sub-nanocpu quantities fail closed.
    """
    from decimal import Decimal, localcontext

    if not isinstance(value, str) or not value or len(value) > 64:
        raise ValueError("Missing or invalid Kubernetes CPU request.")

    match = re.fullmatch(
        r"([0-9]+(?:\.[0-9]+)?|\.[0-9]+)(m|u|n|[eE][+-]?[0-9]{1,3})?",
        value,
    )
    if not match:
        raise ValueError("Unsupported Kubernetes CPU request.")

    suffix = match[2]
    with localcontext() as context:
        context.prec = 80

        if suffix and suffix[0] in "eE":
            cores = Decimal(match[1] + suffix)
        else:
            multiplier = {
                None: Decimal(1),
                "m": Decimal("0.001"),
                "u": Decimal("0.000001"),
                "n": Decimal("0.000000001"),
            }[suffix]
            cores = Decimal(match[1]) * multiplier

        if not cores.is_finite() or not 0 <= cores <= Decimal(1000000):
            raise ValueError("Kubernetes CPU request outside allowed bounds.")

        return nanocpus(format(cores, "f"))


def select_sample(deployments, replicasets, pods, instance):
    expected = {f"{instance}-{name}" for name in COMPONENTS}
    selected = {
        item["metadata"]["uid"]: item["metadata"]["name"]
        for item in deployments
        if item["metadata"]["name"] in expected
    }
    require(
        len(selected) == 6 and set(selected.values()) == expected,
        "Expected all six application Deployments.",
    )

    rs = {
        item["metadata"]["uid"]: selected[owner_uid(item, "Deployment")]
        for item in replicasets
        if owner_uid(item, "Deployment") in selected
    }

    entries = []
    total = 0

    for pod in pods:
        deployment = rs.get(owner_uid(pod, "ReplicaSet"))
        if (
            not deployment
            or pod.get("status", {}).get("phase") != "Running"
            or pod["metadata"].get("deletionTimestamp")
        ):
            continue

        states = {
            item["name"]: item
            for item in pod.get("status", {}).get("containerStatuses", [])
        }

        for container in pod["spec"].get("containers", []):
            state = states.get(container["name"], {})
            if "running" not in state.get("state", {}):
                continue

            amount = kubernetes_nanocpus(
                container.get("resources", {}).get("requests", {}).get("cpu")
            )
            total += amount

            entries.append(
                (
                    deployment,
                    pod["metadata"]["uid"],
                    container["name"],
                    amount,
                    state.get("restartCount", 0),
                    state.get("ready", False),
                )
            )

    signature = json.dumps(
        {
            "deployments": sorted(selected),
            "containers": sorted(entries),
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    return (
        format(Decimal(total) / Decimal(1_000_000_000), "f"),
        hashlib.sha256(signature.encode()).hexdigest(),
    )


def snapshot(config):
    # Re-read the projected token on every request to permit rotation.
    selector = urllib.parse.urlencode(
        {
            "labelSelector": "app.kubernetes.io/instance=" + config["instance"],
            "limit": "1000",
        }
    )

    def listing(api, kind):
        url = (
            "https://kubernetes.default.svc"
            + api
            + "/namespaces/"
            + config["namespace"]
            + "/"
            + kind
            + "?"
            + selector
        )
        document = fetch_json(
            url,
            headers={"Authorization": "Bearer " + TOKEN.read_text().strip()},
            tls=True,
        )
        require(
            not document.get("metadata", {}).get("continue"),
            "Workload list needs pagination; refuse partial measurement.",
        )
        return document["items"]

    return select_sample(
        listing("/apis/apps/v1", "deployments"),
        listing("/apis/apps/v1", "replicasets"),
        listing("/api/v1", "pods"),
        config["instance"],
    )


def agent_status():
    result = fetch_json("http://127.0.0.1:3456/status")
    require(
        result.get("currentFailureCount") == 0 and result.get("totalFailureCount") == 0,
        "Agent reports a disk delivery failure.",
    )
    return result


def report_key(report):
    require(report["name"] == METRIC, "Unexpected metric in disk output.")
    require(report["labels"] == {"test": "disk-only"}, "Unexpected report labels.")
    require(set(report["value"]) == {"doubleValue"}, "Wrong report value type.")

    def timestamp(value):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(parsed.tzinfo is not None, "Missing timestamp timezone.")
        return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")

    return (
        report["name"],
        timestamp(report["startTime"]),
        timestamp(report["endTime"]),
        float(report["value"]["doubleValue"]).hex(),
        json.dumps(report["labels"], sort_keys=True),
    )


def confirm_disk_delivery(box, timeout=30):
    # This is possible because the test destination is on the paired PVC.
    # It is NOT a reconciliation mechanism for Service Control.
    require(
        not box.db.execute(
            "SELECT 1 FROM reports WHERE state IN ('sending','needs_inspection')"
        ).fetchone(),
        "Uncertain sender record requires inspection.",
    )

    expected = Counter(
        report_key(seconds_report(payload.encode()))
        for (payload,) in box.db.execute(
            "SELECT payload FROM reports WHERE state='accepted'"
        )
    )
    deadline = time.monotonic() + timeout

    while True:
        files = list((ROOT / "reports").glob("*.json"))
        require(len(files) <= MAX_SAMPLES, "Disk-report budget exceeded.")
        actual = Counter()

        for file in files:
            require(
                not file.is_symlink() and file.stat().st_size < 100_000,
                "Unexpected disk-report file.",
            )
            actual[report_key(json.loads(file.read_text()))] += 1

        require(
            not (actual - expected),
            "Unexpected or duplicate agent delivery. Stop for inspection.",
        )

        agent_status()

        if actual == expected:
            return
        require(
            time.monotonic() < deadline,
            "Accepted report missing from disk. State loss or delivery failure.",
        )
        time.sleep(1)


def send_once(payload):
    wire = seconds_payload(payload, destination="disk_only")
    request = urllib.request.Request(
        "http://127.0.0.1:3456/report",
        data=wire,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    # One HTTP attempt. No redirect/retry.
    with opener.open(request, timeout=10) as response:
        response.read(4097)
        return response.status


def stamp(milliseconds):
    return (
        (
            datetime(1970, 1, 1, tzinfo=timezone.utc)
            + timedelta(milliseconds=milliseconds)
        )
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def drain(ledger, box):
    rows = ledger.db.execute("""
        SELECT start_ms,end_ms,nano_cpu_ms
        FROM intervals WHERE kind='estimated' ORDER BY start_ms
    """).fetchall()
    require(len(rows) <= MAX_SAMPLES, "Measurement budget exceeded.")

    for start, end, amount in rows:
        box.enqueue(
            {
                "name": "exepno_test_nanocpu_milliseconds",
                "startTime": stamp(start),
                "endTime": stamp(end),
                "value": {"int64Value": int(amount)},
                "labels": {"test": "disk-only"},
            }
        )

    # Resolve previously accepted disk output before admitting another send.
    confirm_disk_delivery(box)

    while not STOP:
        identity = box.send_next(send_once)
        if identity is None:
            break
        confirm_disk_delivery(box)


def main():
    config = configuration()
    initialize()

    deadline = time.monotonic() + 120
    while True:
        try:
            agent_status()
            break
        except Exception:
            require(time.monotonic() < deadline, "Agent startup failed.")
            time.sleep(2)

    scope = json.dumps(config, sort_keys=True)
    sender = ROOT / "sender"
    started = sender / "started.json"

    with ShadowLedger(
        sender / "ledger.sqlite", scope, max_gap_ms=MAX_GAP_MS
    ) as ledger, ShadowOutbox(
        sender / "outbox.sqlite", scope, "paired-local-disk-v1"
    ) as box:
        if not started.exists():
            durable_json(started, {"initialized": True})

        drain(ledger, box)

        epoch = time.time_ns() // 1_000_000
        monotonic = time.monotonic_ns()

        while not STOP:
            count = ledger.db.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
            if count >= MAX_SAMPLES:
                print(
                    "TEST BUDGET COMPLETE: no further sampling or sending.",
                    flush=True,
                )
                # Remain stopped without CrashLoop-driven sampling.
                while not STOP:
                    time.sleep(2)
                break

            begun = time.monotonic()
            cores, topology = snapshot(config)
            require(time.monotonic() - begun <= 15, "Slow sample rejected.")

            timestamp = epoch + (time.monotonic_ns() - monotonic) // 1_000_000
            require(
                abs(timestamp - time.time_ns() // 1_000_000) <= 5000,
                "Wall-clock adjustment requires inspection.",
            )

            outcome = ledger.observe(timestamp, cores, topology)
            drain(ledger, box)
            print(
                json.dumps(
                    {
                        "mode": "disk_only",
                        "sample": count + 1,
                        "cpuRequests": cores,
                        "interval": outcome,
                        "senderStates": box.summary()["states"],
                    }
                ),
                flush=True,
            )

            until = time.monotonic() + INTERVAL_SECONDS
            while not STOP and time.monotonic() < until:
                time.sleep(1)


def stop(*_):
    global STOP
    STOP = True


if __name__ == "__main__":
    import sys

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    try:
        if sys.argv[1:] == ["init"]:
            initialize()
        elif not sys.argv[1:]:
            main()
        else:
            raise RuntimeError("Unknown operation.")
    except Exception:
        # Preserve the original database/outbox state and remain inspectable.
        print(
            "METER HALTED: inspect persistent state and pod logs. "
            "No automatic replay or state reset.",
            flush=True,
        )
        raise
