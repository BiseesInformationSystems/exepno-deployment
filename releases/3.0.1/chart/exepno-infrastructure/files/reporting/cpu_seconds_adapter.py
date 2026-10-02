"""CPU-seconds adapter for the disk-only commercial-format test.

Exact integer ledger quantities remain unchanged.
Conversion to DOUBLE happens only at the outbound reporting boundary.
No Service Control destination is implemented or enabled here.
"""

import json
import math
from decimal import Decimal, localcontext

from ubb_shadow_outbox import normalize_report

SERVICE = "exepno-infrastructure.endpoints.bisees-public.cloud.goog"
METRIC = SERVICE + "/cpu_per_second"
SCALE = 1_000_000_000_000  # nanocpu-milliseconds per CPU-second


def cpu_seconds(amount):
    if (
        not isinstance(amount, int)
        or isinstance(amount, bool)
        or not 0 <= amount <= 2**63 - 1
    ):
        raise ValueError("Expected a nonnegative int64 ledger quantity.")

    with localcontext() as context:
        context.prec = 60

        exact = Decimal(amount) / Decimal(SCALE)
        wire_value = float(exact)

        if not math.isfinite(wire_value):
            raise ValueError("CPU-seconds value is not finite.")

        if amount and wire_value <= 0:
            raise ValueError("Positive usage was lost during conversion.")

        # Permit only the normal binary64 rounding error.
        # Never round upward to whole seconds, minutes or hours.
        difference = abs(Decimal.from_float(wire_value) - exact)
        half_ulp = Decimal.from_float(math.ulp(wire_value)) / 2

        if difference > half_ulp:
            raise ValueError("Unexpected DOUBLE conversion error.")

        return wire_value


def seconds_report(payload, *, destination="disk_only"):
    if destination != "disk_only":
        raise RuntimeError("Live reporting is not enabled by this test adapter.")

    if not isinstance(payload, bytes) or len(payload) > 16384:
        raise ValueError("Expected a bounded JSON payload.")

    source = json.loads(payload)

    # Reuse the tested outbox contract:
    # exact integer quantity, valid timestamps, synthetic test labels.
    _, _, _, canonical = normalize_report(source)
    source = json.loads(canonical)

    return {
        "name": METRIC,
        "startTime": source["startTime"],
        "endTime": source["endTime"],
        "value": {
            "doubleValue": cpu_seconds(source["value"]["int64Value"]),
        },
        "labels": source["labels"],
    }


def seconds_payload(payload, *, destination="disk_only"):
    return json.dumps(
        seconds_report(payload, destination=destination),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
