# Install Exepno Infrastructure

Last updated: 6 October 2026

This guide covers preparing Google Cloud, deploying the Exepno AI workspace
from Marketplace, opening the application and completing administrator
activation.

It does not use the historical Jenkins, Gitea or Airflow installation scripts.

## 1. Contact and release confirmation

Before creating paid infrastructure, confirm the intended release with Bisees:

**Support:** [sales@bisees.com](mailto:sales@bisees.com?subject=Exepno%20installation)

Record:

| Item | Your value |
|---|---|
| Customer Google Cloud project ID | |
| Cloud Billing account | Keep the full ID in your private installation record |
| Cluster name and location | |
| Application namespace | |
| Application instance name | |
| Selected Marketplace release | |
| Selected deployer digest | |
| Administrator email | |

The public Marketplace page can temporarily show an older release while an
update is in progress. If it describes Gitea, Jenkins or the old infrastructure
suite, stop and confirm the replacement release before deploying.

The files under `releases/` are versioned records. Do not assume the historical
`3.0.1` directory automatically matches the latest release selected in
Producer Portal.

## 2. Understand the installation stages

Installation and activation are separate:

1. **Provision infrastructure:** select or create a suitable GKE cluster.
2. **Deploy application:** Marketplace creates the application resources.
3. **Setup state:** the real application and data services start, but normal
   business operations remain unavailable.
4. **Activate:** configure customer identity, approved application accounts
   and model connections.
5. **Accept for use:** test access restrictions, persistence and the workflows
   you intend to enable.

There is no universal administrator password.

A Google Cloud IAM administrator is not automatically an Exepno application
administrator. Creating a Google identity does not by itself create the
required Exepno account mapping.

## 3. Prepare the customer account and permissions

### Billing and purchase

1. Sign in to Google Cloud using the intended customer account.
2. Open **Billing** and select the customer's active billing account.
3. Confirm the product subscription or Private Offer applies to that account.
4. Have the authorized buyer accept the agreed offer, if applicable.

Do not accept an offer under the wrong billing account merely because your
email can access both accounts.

Follow Google's current instructions:

- [Accept a Private Offer](https://docs.cloud.google.com/marketplace/docs/offers/accepting-private-offer)
- [Manage billing-account permissions](https://docs.cloud.google.com/billing/docs/how-to/grant-access-to-billing)

Software charges, GCP infrastructure charges and model-provider usage are
separate. Your accepted order governs the software pricing and commitments.

### Deployment access

The deploying operator needs the Google and Kubernetes permissions required
to install the application. Google's Marketplace guide lists Kubernetes
Engine Admin plus Project Viewer as a supported role combination.

Cluster creation, node service-account use and workload identity can require
additional scoped permissions. Ask your platform administrator to assign
them; do not grant Owner indiscriminately.

## 4. Select the project and control spending

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Select an approved customer project, or create a dedicated project.
3. Confirm its billing-account association.
4. Agree the region and data-location requirements.
5. Review CPU, memory, disk and networking quotas.
6. Create a project-scoped budget and alerts.
7. Record who owns operational costs and incident response.

Budget alerts are not automatic spending caps.

Do not use Bisees development projects, credentials or user lists as customer
installation defaults.

## 5. Prepare Kubernetes

### If you already have a cluster

Ask the platform administrator to verify:

- Compatibility with the selected Exepno release.
- Linux AMD64 capacity for the shipped images.
- Enough allocatable CPU and memory for all application requests.
- Persistent Disk CSI support and a compatible storage class.
- Access to the required container registries.
- Appropriate workload identity and network configuration.
- Capacity for startup peaks and model-cache downloads.

Do not infer Autopilot or ARM compatibility merely because the chart renders.

### If you need a new cluster

You can create it through the Marketplace **Configure → Create cluster**
option, or through **Kubernetes Engine → Clusters → Create**.

For the previously tested baseline, use GKE Standard and Linux AMD64 nodes.
Follow the current Google cluster-creation guide:

[Create a GKE Standard zonal cluster](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/creating-a-zonal-cluster)

In the creation screen:

1. Enter a unique cluster name.
2. Select the agreed region/zone and release channel.
3. Select the node pool and machine configuration.
4. Confirm sufficient total CPU, memory and disk capacity.
5. Enable the required Workload Identity Federation configuration.
6. Select an approved node service account with registry and operational access.
7. Review control-plane access restrictions and administrator connectivity.
8. Review the estimated cost before clicking **Create**.

Our engineering installation used one `e2-standard-8` node.
That is a reference test configuration—not a guaranteed production minimum
or a high-availability design.

A regional cluster can create node pools across multiple zones. Check the
total node count, not only a per-zone setting.

Do not create GPUs unless an agreed inference workload needs them.

Google currently documents a `default` network prerequisite for its
Marketplace Console deployment flow. If organization policy prohibits this
or the cluster is marked ineligible, have the platform administrator resolve
the prerequisite rather than bypass network controls.

## 6. Deploy from Marketplace

1. Open **Marketplace** in the customer project.
2. Search for **Exepno Infrastructure**, published by Bisees Information Systems.
3. Confirm the overview describes the intended AI workspace release.
4. Click **Configure**.
5. Select the approved cluster.
6. Select or create a dedicated namespace, for example `exepno-prod`.
   Do not use a namespace ending in `-system`.
7. Enter a unique instance name, for example `exepno-team`.
8. Review the selected version, storage settings and plan configuration.
9. If the release exposes **Installation state**, choose `setup` for a fresh
   installation unless the configured-mode prerequisites have already been
   completed.
10. Review all values, then click **Deploy**.

The setup-enabled package generates installation storage credentials.
Do not replace them with example passwords or publish them in Git.

If the deployment form instead requires existing runtime Secrets and an
administrator UID, verify the selected release with Bisees before proceeding.
Do not enter the name of a Secret that does not exist.

Official procedure:

[Deploy Kubernetes applications from Marketplace](https://docs.cloud.google.com/marketplace/docs/kubernetes-apps)

## 7. Check the installation

In Google Cloud Console, open **Kubernetes Engine → Applications** and select
the new instance.

Check:

- Installer and initialization Job results.
- Frontend, backend and gateway readiness.
- MongoDB, MinIO and Qdrant readiness.
- Persistent volume claims are `Bound`.
- No repeated container restarts or unresolved scheduling errors.

An installer Job completing does not necessarily mean all application pods
are ready.

If installation fails, preserve its resources and inspect the first failure.
Do not delete operation receipts, recreate accounts or regenerate passwords
to force a fresh attempt.

## 8. Connect from your Mac

Install Google Cloud CLI, kubectl and the GKE authentication plugin using
Google's instructions:

[Install kubectl and configure GKE access](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/cluster-access-for-kubectl)

You do not need the private Exepno source code or a local application server.

Replace the uppercase placeholders below before running:

```bash
gcloud auth login

gcloud container clusters get-credentials YOUR_CLUSTER \
  --project=YOUR_PROJECT_ID \
  --location=YOUR_CLUSTER_REGION_OR_ZONE

kubectl config current-context

kubectl -n YOUR_NAMESPACE get deployments,pods,pvc,jobs
kubectl -n YOUR_NAMESPACE get services
```

Confirm the context belongs to the intended customer cluster.

Find the Service ending in `-gateway`. In a separate terminal:

```bash
kubectl -n YOUR_NAMESPACE \
  port-forward service/YOUR_INSTANCE-gateway 8081:8080 \
  --address=127.0.0.1
```

Keep this terminal open and visit:

```text
http://127.0.0.1:8081/
```

Port forwarding gives this computer temporary access. It does not create a
public endpoint. Closing the terminal or sleeping the Mac can interrupt the
tunnel while the cloud application continues running.

If using Cloud Shell, its `localhost` is not your Mac's `localhost`.
Use Cloud Shell's approved preview procedure or the local CLI route above.

## 9. Complete administrator activation

### If `/setup` appears

This is the expected restricted state of a fresh setup-enabled installation.
No Google user is automatically authenticated.

The customer administrator must arrange:

1. Identity Platform in the intended customer project.
2. Email/password sign-in configuration.
3. An existing enabled Google identity or a newly created customer identity.
4. The public authentication web configuration.
5. Scoped workload access to required Google services and provider secrets.
6. The initial Exepno account mapping and administrator role.
7. The release-specific transition to configured mode.

Use the supported activation procedure supplied for your release.
If it is not included in the release documentation, contact
[sales@bisees.com](mailto:sales@bisees.com?subject=Exepno%20activation).

**Do not change `EXEPNO_INSTALLATION_MODE` to `configured` by itself.**
That does not provision identity, permissions or accounts.

Preserve the generated database passwords and application encryption key.
Reusing existing storage with newly generated credentials can make the
installation unusable.

### If the login form appears

Sign in with the email/password belonging to that installation's configured
Identity Platform project.

Do not enter the Google UID in the email field.
Do not use an account from a different project merely because the email
address is familiar.

## 10. Provision ordinary users

The supported account path must create or identify both:

- The Google identity.
- Its active Exepno application mapping.

If your release enables **Integrations → Administration → Create user**,
use that operator-approved workflow and verify the target identity project.

If the control is disabled or absent, use the release-specific provisioning
procedure with your identity/platform administrator or Bisees support.
Do not enable write flags or grant broad cloud permissions merely to make
the button active.

For each test user:

1. Verify sign-in.
2. Save and reopen their own conversation.
3. Confirm they cannot access Administration.
4. Confirm they cannot retrieve or delete another user's conversation.
5. Grant document/group access separately.

No purchased balance or synthetic credit should be invented during user setup.

## 11. Configure and test integrations

Follow [Configuration](configuration.md) and the integration guides exposed
by your application.

Begin with synthetic data and a disposable repository.

Test only the capabilities enabled for the installed release:

- A supported model response, save and reload.
- Document upload, preview and authorized source access.
- A configured read-only structured-data query.
- Repository review before enabling change proposals.
- Optional Jira operations only with explicit approval.

Keep the existing application guide paths:

- `/guides/noetic-integrations-setup.html`
- `/guides/noetic-validation-environments.html`

These paths belong to your application hostname. Their legacy filenames do
not require renaming.

Hosted-model requests leave the cluster. Review provider terms and permitted
data before uploading confidential material.

## 12. Production and cost checkpoint

Before production:

- Configure approved HTTPS access; port forwarding is for private testing.
- Test configured-mode authorization and cross-user isolation.
- Verify enabled file/download routes are protected.
- Define backups and test restoration.
- Preserve matching credentials and encryption keys.
- Review current image-security evidence.
- Agree workload sizing, availability and support responsibilities.
- Confirm the software reporting and commercial configuration.

Do not expose MongoDB, MinIO administration or Qdrant directly to the internet.

For GKE Standard node-pool autoscaling:

1. Open the cluster's **Nodes** tab.
2. Select the node pool and choose **Edit**.
3. Enable autoscaling and review minimum/maximum bounds.
4. Check whether the bounds apply per zone or across the pool.
5. Observe scheduling and application health after saving.

Follow the current official guidance:

[Configure cluster autoscaling](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/cluster-autoscaler)

Node autoscaling does not turn single-replica databases into highly available
services. Do not add database replicas or shrink nodes without a supported
stateful-workload plan.

Closing your laptop does not stop GKE, disk or registry charges.

## 13. Recovery and removal

Follow [Data lifecycle](data-lifecycle.md).

Choose explicitly between:

- Removing the application while retaining data and recovery configuration.
- Permanently purging approved installation-owned storage.

Do not use `kubectl delete pvc --all`, remove finalizers, or delete the
namespace as a generic troubleshooting instruction.

An image rollback does not reverse database writes or document reprocessing.
A Helm-release uninstall tool is not automatically applicable to a
Marketplace installation created from rendered manifests.

Review the Marketplace order separately: infrastructure removal and
contract cancellation are different operations.

## 14. CLI deployment assets and historical material

This repository provides deployment configuration for release inspection and
the supported CLI workflow. Do not execute an old frozen `mpdev` command until
its digest, parameters and prerequisite procedure have been reconciled with
the selected customer release.

The historical
[Exepno-Infrastructure repository](https://github.com/BiseesInformationSystems/Exepno-Infrastructure)
is retained for reference only. Its Pulumi scripts, service-account-key
workflow, old infrastructure components and deletion commands are not part
of this installation procedure.

## Support

**Bisees Information Systems**  
6–9 Trinity Street  
Dublin D02 EY47, Ireland

Email: [sales@bisees.com](mailto:sales@bisees.com?subject=Exepno%20support)

Include the release, deployment stage, expected result, actual result and
sanitized error details. Never send passwords, tokens, provider keys,
reporting credentials or confidential documents in an initial request.
