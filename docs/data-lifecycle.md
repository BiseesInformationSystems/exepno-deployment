# Data lifecycle and removal

## Different data categories require different operations

Conversation deletion is not necessarily removal of shared documents,
vector records, generated artifacts, accounting records or external copies.

Deleting a user profile in a document store does not delete a Google identity.

## Retaining installation data

Retain-data removal should stop the application while preserving the
persistent stores and the configuration needed to reuse them:
- MongoDB, MinIO and Qdrant data
- Required storage credentials
- Application encryption keys
- Authentication configuration
- Claim and volume identities

Storage charges may continue. Retention is not a backup.

## Reinstallation

Use the original claims and matching credentials through the reviewed
recovery procedure. Do not reset passwords, account status or balances
automatically.

Application identity and reporting-state bindings may require explicit
recovery review after an Application resource is recreated.

## Permanent purge

Purge must identify exact installation-owned claims and disks, stop their
consumers, require confirmation and verify the resulting deletion.

Never use namespace deletion, `delete pvc --all` or forced finalizer removal
as a general-purpose uninstall instruction.

Google identities, external secrets, external stores and independent
backups are outside a storage purge unless separately authorized.

## Validation boundary

Retain/reinstall/purge passed on a separate engineering Helm installation.
That is not a complete Marketplace removal certification.

The package sets Application.addOwnerRef=false. This does not prove that
the deployer has assigned no owner references to other resources.
Inspect actual deployed ownership before removing the Application.

Do not use the Helm-release-based uninstall tool on an installation that
has no corresponding Helm release. Marketplace-path recovery and removal
remain release gates.
