# Troubleshooting

Record the release version, deployer digest, application name, namespace
and the first relevant sanitized error.

## Installer failure

Separate schema expansion, rendering, Kubernetes admission, scheduling,
bootstrap and application readiness.

Do not blindly resubmit after partial installation.
Preserve the namespace, credentials, operation receipts and installer logs.

## Initialization failure

Check data-service readiness, project configuration, Google identity,
secret access and existing mappings.

Do not automatically reclaim interrupted receipts or remove data to get
a clean test result.

## Authentication

Google sign-in, server token verification, active application mapping
and administrator-role checks are different boundaries.

A Cloud IAM administrator is not automatically an Exepno administrator.

## Documents and images

Separate extraction, generated HTML, storage access and browser delivery.
Broken images do not necessarily mean extraction failed.
Reusing a cached document may retain an older rendering format.

Do not make private storage public or remove route authentication as a fix.

## Metering

Internal prepaid-credit policy is separate from Marketplace software usage.
Do not change metric units or reset reporting state to silence an error.
An agent HTTP acknowledgment is not an individual Google billing receipt.

## Capacity

Inspect Pending reasons, requested resources and storage events.
Do not remove resource requirements or storage finalizers just to force readiness.

## Support

Provide reproduction steps and sanitized logs.
Never send passwords, bearer tokens, private reporting keys, provider-secret
payloads or confidential documents in an initial request.
