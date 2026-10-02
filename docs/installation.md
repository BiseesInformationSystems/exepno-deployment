# Installation

## Status

This document describes the prerequisites for the staged 3.0.1 candidate.
It is not yet a complete customer installation procedure.

Executable installation, recovery and removal instructions will be added
after the corresponding Marketplace deployment tests are complete.
Do not use this candidate with production data.

The exact staged installer is recorded in
[`release.json`](../releases/3.0.1/release.json).
A frontend image is not a deployer.

## Prerequisites

1. A suitable x86-64 GKE environment with sufficient compute and persistent storage.
2. A dedicated namespace and unique application instance name.
3. Identity Platform in the deployment project, with email/password sign-in configured.
4. An existing enabled Google identity explicitly selected as initial administrator.
5. Customer-owned provider credentials in Secret Manager.
6. Customer-prepared runtime and Mongo initialization Secrets.
7. A workload service account with the required identity/secret access.
8. Registry image-pull access and an available CSI storage class.
9. Recovery and cost ownership agreed before installation.

Use configuration and credentials created for your organization and installation.
Keep passwords, private keys and provider credentials out of Git and container images.

## Inspect the configuration locally

From this repository root:

```bash
cat releases/3.0.1/release.json
cat releases/3.0.1/schema.yaml
cat releases/3.0.1/chart/exepno-infrastructure/values.yaml
```

The deployment schema is the authoritative input-name reference.
Image references are generated/substituted by the Marketplace deployer.

## CLI installation status

The installer path uses Google's `mpdev install` with the pinned deployer
and a reviewed parameters file. Customer-ready executable instructions
will be published after the remaining prerequisite, reporting and
removal checks pass.

Do not substitute `helm install` and assume it exercises the same lifecycle.
Do not execute historical 2.0 provisioning scripts for this release.

## Initialization contract

The package validates the selected project and existing Google identity,
then initializes missing application storage and administrator mapping.

It does not create Google users, change passwords, grant initial credits
or intentionally install a public object-storage policy.

An incomplete or conflicting initialization receipt requires inspection.
Do not delete the receipt or regenerate credentials to force a retry.

## Initial acceptance

Before normal use, verify:
- Administrator sign-in and ordinary-user restrictions.
- A supported model request.
- Save, reload and persistence after a workload restart.
- Cross-user read/delete denial.
- Authorized document/file delivery for enabled workflows.
- Reporting configuration and installation-data recovery.

GPU provisioning, public HTTPS ingress and external callback endpoints
are separate configuration decisions.
