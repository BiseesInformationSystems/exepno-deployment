# Release acceptance checklist

Status: staged package; not a completed customer-release approval.

## Package
- [ ] Final deployer and all referenced images recorded by digest.
- [ ] Source, schema, Application and chart versions agree.
- [ ] Marketplace image substitution verified for the final package.
- [ ] Required manifest annotations verified on all shipped images.
- [ ] Customer-profile installation and initialization verified.

## Security and functionality
- [ ] Current scans assessed for every shipped digest.
- [ ] Required framework/library updates tested.
- [ ] Enabled APIs and generated/uploaded file delivery authorized.
- [ ] Cross-user read/delete denial verified.
- [ ] Advertised PDF, image and optional workflows accepted.
- [ ] No sensitive material in distributable images or repository files.

## Billing
- [ ] Approved metric remains cpu_per_second with seconds reporting.
- [ ] CPU measurement semantics confirmed.
- [ ] Continuous-production reporting replaces the controlled-test budget.
- [ ] Customer reporting identity and persistent-state boundaries tested.
- [ ] Failure/reconciliation and uninstall reporting behavior verified.

## Data lifecycle
- [ ] Marketplace removal tested separately from Helm uninstall.
- [ ] Retained data and credentials recoverable.
- [ ] Explicit purge affects only authorized installation-owned storage.
- [ ] Backups and external resources documented separately.

## Documentation and licensing
- [ ] Executable customer CLI instructions validated.
- [ ] Support contact and policy approved.
- [ ] Repository license selected by the rights holder.
- [ ] Upstream notices and source-distribution obligations reviewed.
- [ ] All documentation matches the final accepted package.

## Publication
- [ ] Explicit human approval of final release record.
- [ ] Producer Portal validation reviewed.
- [ ] Submission and publication performed deliberately.

A staged registry tag, passing lint or a working login is not proof that
all these gates passed.
