# Configuration

## Identity and project ownership

The customer-profile bootstrap requires the workload, authentication and
provider-secret project to agree.

Public web-authentication settings:
- `NOETIC_AUTH_PROJECT_ID`
- `NOETIC_AUTH_API_KEY`
- `NOETIC_AUTH_DOMAIN`

These are not private model-provider keys.

## Provider secrets

`NOETIC_SECRET_VERSION` identifies a numeric Secret Manager version.
Do not include its payload in Helm values, images or this repository.

This candidate's initialization currently requires both OPENAI_API_KEY and
GEMINI_API_KEY in the configured JSON secret bundle. Have these available
before installation, even if your first workflow uses only one provider.

Use provider accounts authorized by your organization. Requests made with
those credentials are charged according to the corresponding provider account.

The workload identity needs the relevant Google permissions.
A copied service-account private key is not the default authentication method.

## Namespace-local data

The Mongo URI must reference the correct instance-specific MongoDB Service.
Its password must match the application password in the Mongo initialization
Secret. Preserve both on reinstallation.

The chart supplies instance-specific MinIO and Qdrant hosts.
MinIO credentials and application encryption keys remain customer secrets.

Changing `NOETIC_CONNECTIONS_KEY` can make existing encrypted connections
unreadable. It is not a routine branding or reinstall change.

## Internal credits and Marketplace billing

`EXEPNO_CREDIT_MODE=customer_keys` bypasses the internal prepaid token-credit
system. It does not establish ownership of the configured keys or implement
Marketplace usage reporting.

The Marketplace reporting Secret is separate and contains:
- `entitlement-id`
- `consumer-id`
- `reporting-key`

Never substitute provider credentials for that reporting key.
The staged package defaults to disabled disk reporting; do not describe
that configuration as continuous commercial reporting.

## Optional features

Image analysis requires an explicitly configured supported model.
Document, structured-data, repository and other connections must be
configured and tested separately.

Oracle and SQL Server are optional customer integrations.
Server TTS is not installed in this release candidate.

## Private configuration handling

Never commit customer parameter files containing secrets.
Review logs before sharing. Do not expose provider keys in browser variables.
Do not make a bucket public to repair a document-preview failure.
