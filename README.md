# Exepno Infrastructure

**Your business context. Your model connections. Your AI workspace.**

Exepno is deployed in the customer's Google Cloud environment.
This repository contains deployment configuration and operator documentation.
It includes deployment templates and the bootstrap/reporting helpers required
by those templates. It does not include the frontend or backend application
source trees.

## Release status

Version **3.0.1** is staged under track **3.0**.
It is not yet established as an approved replacement customer release.

See [the release record](releases/3.0.1/release.json) and
[acceptance checklist](RELEASE-CHECKLIST.md).
Historical release 2.0 belongs to the previous infrastructure package.

## Deployment components

- Next.js frontend and application APIs
- Python FastAPI backend
- MongoDB
- MinIO-compatible object storage
- Qdrant
- Nginx gateway
- Optional reporting workload, disabled by default in this candidate



## Processing and cost boundaries

Customer-hosted deployment does not automatically mean local-only inference.
Requests sent to hosted model providers are processed outside the cluster.
Customers configure their identities, model connections and credentials.

The recorded Marketplace software plan is USD 0.0561 per CPU-hour.
Cloud infrastructure and model-provider charges are separate.
Commercial metering and its measurement definition remain release gates.

## Documentation

- [Installation](docs/installation.md)
- [Configuration](docs/configuration.md)
- [Data lifecycle](docs/data-lifecycle.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Release acceptance](RELEASE-CHECKLIST.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)

## Support

Publisher: **Bisees Information Systems**.

Contact: **sales@bisees.com**. Include the release and affected workflow,
but do not email passwords, private keys, tokens or confidential documents
in an initial request. Service levels depend on the applicable agreement.

## Licensing

Any license in this repository applies only within its stated scope.
It does not grant a license to private Exepno application source or replace
the application EULA and third-party component licenses.

Do not treat repository publication as Marketplace product approval.
