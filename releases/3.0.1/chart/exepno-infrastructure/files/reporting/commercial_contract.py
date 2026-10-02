"""Commercial reporting configuration and persistent identity binding.

No HTTP requests, credential lookup, agent execution or live billing.
Secret contents must never be logged or committed.

A populated billing state directory without its binding is NOT adopted.
Changing customer/installation/measurement identity requires inspection.
"""

import base64
import fcntl
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

SERVICE = "exepno-infrastructure.endpoints.bisees-public.cloud.goog"
METRIC = SERVICE + "/cpu_per_second"


def require(condition, code):
    if not condition:
        raise ValueError(code)


def identifier(value, label, maximum=512):
    require(
        isinstance(value, str)
        and 0 < len(value) <= maximum
        and value == value.strip()
        and not re.search(r"[\x00-\x20\x7f]", value),
        "invalid_" + label,
    )
    return value


def reporting_credentials(fields):
    """Validate values AFTER Kubernetes Secret projection/decoding.

    reporting-key may contain the JSON key itself or its documented
    agent-compatible base64 representation. Normalize to base64(JSON).

    This checks structure, not cryptographic validity or entitlement status.
    """
    require(
        isinstance(fields, dict)
        and set(fields) == {"entitlement-id", "consumer-id", "reporting-key"},
        "invalid_reporting_secret_fields",
    )

    entitlement = identifier(fields["entitlement-id"], "entitlement")
    consumer = identifier(fields["consumer-id"], "consumer")

    raw = fields["reporting-key"]
    require(
        isinstance(raw, str) and 0 < len(raw) <= 65536,
        "invalid_reporting_key",
    )

    try:
        if raw.lstrip().startswith("{"):
            key_bytes = raw.encode("utf-8")
        else:
            key_bytes = base64.b64decode(raw.strip(), validate=True)

        def unique_fields(pairs):
            result = {}
            for name, value in pairs:
                if name in result:
                    raise ValueError("duplicate_key")
                result[name] = value
            return result

        key = json.loads(
            key_bytes.decode("utf-8"),
            object_pairs_hook=unique_fields,
        )
    except Exception:
        raise ValueError("invalid_reporting_key_encoding") from None

    require(isinstance(key, dict), "invalid_reporting_key_object")
    require(key.get("type") == "service_account", "wrong_credential_type")

    email = identifier(key.get("client_email"), "reporting_identity")
    client_id = identifier(key.get("client_id"), "reporting_client_id")

    require(
        email.endswith(".gserviceaccount.com") and "@" in email,
        "invalid_reporting_identity",
    )
    require(
        isinstance(key.get("private_key"), str)
        and key["private_key"].startswith("-----BEGIN PRIVATE KEY-----\n")
        and key["private_key"].rstrip().endswith("-----END PRIVATE KEY-----"),
        "invalid_private_key_structure",
    )
    require(
        key.get("token_uri") == "https://oauth2.googleapis.com/token",
        "unexpected_token_endpoint",
    )
    identifier(key.get("private_key_id"), "private_key_id")

    # Do not assert that this reporting account belongs to the customer's
    # project. Marketplace supplies it for the product's reporting channel.
    encoded_key = base64.b64encode(key_bytes).decode("ascii")

    return {
        "entitlementId": entitlement,
        "consumerId": consumer,
        "clientEmail": email,
        "clientId": client_id,
        "encodedKey": encoded_key,
    }


def installation_binding(scope, fields, measurement_definition):
    require(
        isinstance(scope, dict)
        and set(scope) == {"projectId", "namespace", "instance", "applicationUid"},
        "invalid_installation_scope",
    )

    normalized_scope = {name: identifier(value, name) for name, value in scope.items()}
    definition = identifier(
        measurement_definition, "measurement_definition", maximum=200
    )
    credentials = reporting_credentials(fields)

    # No private key or key ID: rotating a key for the same reporting
    # identity must not silently create a new billable installation.
    return {
        "schemaVersion": 1,
        "destination": "google_service_control",
        "service": SERVICE,
        "metric": METRIC,
        "unit": "s",
        "valueType": "DOUBLE",
        "measurementDefinition": definition,
        "installation": normalized_scope,
        "customer": {
            "entitlementId": credentials["entitlementId"],
            "consumerId": credentials["consumerId"],
        },
        "reportingIdentity": {
            "clientEmail": credentials["clientEmail"],
            "clientId": credentials["clientId"],
        },
    }


def build_agent_configuration(
    scope, fields, measurement_definition, *, live_authorized=False
):
    """Pure configuration builder. Does not write or start an agent.

    live_authorized must be an explicit operator-controlled decision.
    It is NOT proof of Google's approval of the measurement definition.
    """
    require(live_authorized is True, "live_reporting_not_authorized")

    binding = installation_binding(scope, fields, measurement_definition)
    credentials = reporting_credentials(fields)

    config = {
        "identities": [
            {
                "name": "marketplace",
                "gcp": {
                    "encodedServiceAccountKey": credentials["encodedKey"],
                },
            }
        ],
        "metrics": [
            {
                "name": METRIC,
                "type": "double",
                "passthrough": {},
                "endpoints": [{"name": "servicecontrol"}],
            }
        ],
        "endpoints": [
            {
                "name": "servicecontrol",
                "servicecontrol": {
                    "identity": "marketplace",
                    "serviceName": SERVICE,
                    # Preserve exactly what Marketplace supplied.
                    "consumerId": credentials["consumerId"],
                },
            }
        ],
    }

    return config, binding


def bind_state(directory, binding):
    """Write once, then require an identical binding.

    Use a NEW commercial state directory, not the disk-test state.
    This is a local-filesystem guard, not distributed leader election.
    """
    supplied = Path(directory).expanduser()
    require(not supplied.is_symlink(), "state_directory_is_symlink")

    supplied.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory = supplied.resolve()

    marker = directory / "binding.json"
    lock_path = directory / ".binding.lock"

    require(
        not marker.is_symlink() and not lock_path.is_symlink(),
        "state_file_is_symlink",
    )

    encoded = (
        json.dumps(binding, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")

    with lock_path.open("a+b") as lock:
        lock_path.chmod(0o600)

        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("another_binding_operation_is_running")

        if marker.exists():
            require(marker.is_file(), "invalid_binding_file")
            require(
                marker.read_bytes() == encoded,
                "billing_identity_changed_requires_inspection",
            )
        else:
            # Never adopt an unknown ledger, agent queue or prior customer.
            unexpected = [
                item
                for item in directory.iterdir()
                if item.name not in {".binding.lock", "lost+found"}
            ]
            require(not unexpected, "unbound_state_is_not_empty")

            descriptor, temporary = tempfile.mkstemp(
                prefix=".binding-pending-", dir=directory
            )
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())

                # No overwrite of an existing binding.
                os.link(temporary, marker)

                directory_fd = os.open(str(directory), os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                Path(temporary).unlink(missing_ok=True)

    return hashlib.sha256(encoded).hexdigest()
