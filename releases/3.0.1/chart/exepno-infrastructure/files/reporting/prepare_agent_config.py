"""Prepare private UBB configuration. No network or reporting operations.

Production entrypoint requires:
- A projected Marketplace reporting Secret.
- A NEW commercial state directory, never the disk-test state.
- A memory-backed configuration directory.
- Explicit operator authorization.

This does not establish credential validity, entitlement validity,
approved CPU semantics or downstream delivery.
"""

import json
import os
import re
import tempfile
from pathlib import Path

from commercial_contract import (
    bind_state,
    build_agent_configuration,
)

SECRET_FIELDS = ("entitlement-id", "consumer-id", "reporting-key")


def read_reporting_secret(directory):
    """Allow Kubernetes projected-Secret symlinks only within the mount."""
    directory = Path(directory).resolve(strict=True)

    if not directory.is_dir():
        raise ValueError("reporting_secret_directory_missing")

    result = {}
    limits = {
        "entitlement-id": 512,
        "consumer-id": 512,
        "reporting-key": 65536,
    }

    for name in SECRET_FIELDS:
        file = (directory / name).resolve(strict=True)

        # Projected Secret keys normally resolve through ..data symlinks.
        # Do not reject those, but prohibit escaping the mounted directory.
        if directory not in file.parents or not file.is_file():
            raise ValueError("invalid_projected_secret_path")

        with file.open("rb") as handle:
            data = handle.read(limits[name] + 1)

        if not data or len(data) > limits[name]:
            raise ValueError("invalid_projected_secret_size")

        result[name] = data.decode("utf-8")

    return result


def require_tmpfs(directory, mountinfo="/proc/self/mountinfo"):
    """Require the output directory's covering Linux mount to be tmpfs."""
    directory = Path(directory).resolve(strict=True)
    best = None

    def unescape(value):
        return re.sub(
            r"\\([0-7]{3})",
            lambda match: chr(int(match[1], 8)),
            value,
        )

    for line in Path(mountinfo).read_text().splitlines():
        before, separator, after = line.partition(" - ")
        if not separator:
            continue

        fields = before.split()
        filesystem = after.split()[0]
        if len(fields) < 5:
            continue

        mount = Path(unescape(fields[4]))

        if directory == mount or mount in directory.parents:
            if best is None or len(mount.parts) > len(best[0].parts):
                best = (mount, filesystem)

    if best is None or best[1] != "tmpfs":
        raise RuntimeError("agent_configuration_requires_memory_backed_mount")


def prepare_configuration(
    secret_directory,
    state_directory,
    config_directory,
    scope,
    measurement_definition,
    *,
    authorized=False,
):
    """Pure local-file preparation; caller must enforce mount policy."""
    if authorized is not True:
        raise RuntimeError("commercial_configuration_not_authorized")

    fields = read_reporting_secret(secret_directory)

    # Validate before writing persistent identity or private configuration.
    config, binding = build_agent_configuration(
        scope,
        fields,
        measurement_definition,
        live_authorized=True,
    )

    output_directory = Path(config_directory)
    if output_directory.is_symlink() or not output_directory.is_dir():
        raise RuntimeError("invalid_agent_configuration_directory")

    target = output_directory / "agent-config.yaml"
    if target.is_symlink():
        raise RuntimeError("refusing_linked_configuration_file")

    # Refuses adopting disk-test data or a different customer/installation.
    binding_hash = bind_state(state_directory, binding)

    # JSON is a YAML-compatible representation; avoid injecting credentials
    # into a hand-assembled YAML string.
    payload = (json.dumps(config, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )

    descriptor, temporary = tempfile.mkstemp(
        prefix=".agent-config-", dir=output_directory
    )

    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temporary, target)

        directory_fd = os.open(str(output_directory), os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        Path(temporary).unlink(missing_ok=True)

    # No credential values or complete configuration returned to the log.
    return {
        "configurationWritten": True,
        "bindingSha256": binding_hash,
        "agentStarted": False,
        "usageSubmitted": False,
    }


def main():
    os.umask(0o077)

    if os.environ.get("EXEPNO_COMMERCIAL_REPORTING_AUTHORIZED") != "true":
        raise RuntimeError("commercial_configuration_not_authorized")

    scope = {
        "projectId": os.environ["EXEPNO_CUSTOMER_PROJECT"],
        "namespace": os.environ["EXEPNO_NAMESPACE"],
        "instance": os.environ["EXEPNO_INSTANCE"],
        "applicationUid": os.environ["EXEPNO_APPLICATION_UID"],
    }

    output = Path("/run/exepno-agent-config")
    require_tmpfs(output)

    result = prepare_configuration(
        "/run/exepno-reporting-secret",
        "/billing-state",
        output,
        scope,
        os.environ["EXEPNO_CPU_MEASUREMENT_DEFINITION"],
        authorized=True,
    )

    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Never expose key parsing details or request/configuration content.
        print(
            "REPORTING CONFIGURATION FAILED. "
            "Inspect configuration and binding; do not reset persistent state."
        )
        raise SystemExit(1)
