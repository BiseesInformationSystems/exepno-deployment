const { randomUUID } = require("node:crypto");
const { MongoClient } = require("/app/node_modules/mongodb");
const { Client: MinioClient } = require("/app/node_modules/minio");
const { googleAuth } = require("/app/src/lib/auth/server.cjs");
const { getRequiredSecret } = require("/app/src/lib/serverSecrets.cjs");
const {
  configuration, verifyProject, verifyAccount,
  verifyVector, receiptMatches, requireCondition,
} = require("./contract.cjs");

let stage = "configuration";
let mongo;
let receipts;
let receiptId;
let operationId;
let claimed = false;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitFor(label, operation) {
  stage = label;
  const deadline = Date.now() + 180000;

  while (Date.now() < deadline) {
    try {
      return await operation();
    } catch {
      await sleep(3000);
    }
  }

  const error = new Error("dependency_unavailable");
  error.code = "dependency_unavailable";
  throw error;
}

async function metadata(key) {
  const response = await fetch(
    "http://metadata.google.internal/computeMetadata/v1/project/" + key,
    {
      headers: { "Metadata-Flavor": "Google" },
      redirect: "error",
      signal: AbortSignal.timeout(10000),
    },
  );

  requireCondition(response.ok, "metadata_lookup_failed");
  return (await response.text()).trim();
}

async function main() {
  const config = configuration(process.env);

  // Validate the actual workload project, not only a user-supplied value.
  stage = "workload_project";
  const [project, number] = await Promise.all([
    metadata("project-id"), metadata("numeric-project-id"),
  ]);
  verifyProject(config, project, number);

  stage = "google_identity";
  const user = await googleAuth().getUser(config.admin);
  requireCondition(
    user.uid === config.admin && !user.disabled && Boolean(user.email),
    "administrator_identity_unavailable",
  );

  stage = "provider_secret";
  // Availability only: no prompt or paid model-generation call.
  await getRequiredSecret("OPENAI_API_KEY");
  await getRequiredSecret("GEMINI_API_KEY");

  mongo = new MongoClient(config.mongoUri, {
    maxPoolSize: 2,
    serverSelectionTimeoutMS: 5000,
    connectTimeoutMS: 5000,
    socketTimeoutMS: 15000,
  });

  await waitFor("mongodb_readiness", async () => {
    await mongo.connect();
    await mongo.db("exepno").command({ ping: 1 });
  });

  const db = mongo.db("exepno");
  const accounts = db.collection("noetic_accounts");
  receipts = db.collection("exepno_installations");
  receiptId = config.receiptId;

  const storage = new MinioClient({
    endPoint: config.minioHost,
    port: 9000,
    useSSL: false,
    accessKey: process.env.MINIO_ACCESS_KEY,
    secretKey: process.env.MINIO_SECRET_KEY,
  });

  let bucketExists = await waitFor(
    "object_storage_readiness",
    () => storage.bucketExists(config.bucket),
  );

  const endpoint =
    `http://${config.qdrantHost}:6333/collections/rag_collection`;

  async function readVector() {
    const response = await fetch(endpoint, {
      redirect: "error",
      signal: AbortSignal.timeout(10000),
    });

    if (response.status === 404) {
      await response.body?.cancel();
      return null;
    }

    requireCondition(response.ok, "vector_lookup_failed");
    return response.json();
  }

  let vector = await waitFor("vector_readiness", readVector);

  stage = "existing_state_validation";
  if (vector) verifyVector(vector);

  const account = await accounts.findOne({ _id: config.admin });
  verifyAccount(account, config, user.email);

  // Do not silently introduce another first administrator to an existing DB.
  if (!account) {
    requireCondition(
      !(await accounts.findOne({ roles: "admin" })),
      "existing_administrator_requires_review",
    );
  }

  const previous = await receipts.findOne({ _id: receiptId });

  if (previous) {
    requireCondition(
      receiptMatches(previous, config),
      "installation_identity_conflict",
    );
    requireCondition(
      previous.status === "complete",
      "previous_initialization_requires_inspection",
    );
    requireCondition(
      Boolean(account) && bucketExists && Boolean(vector),
      "completed_installation_missing_resources",
    );

    console.log("PASS: existing installation and administrator revalidated.");
    return;
  }

  operationId = randomUUID();

  // Claim the operation before its first application/storage mutation.
  // A competing or uncertain reservation is never reclaimed automatically.
  await receipts.insertOne({
    _id: receiptId,
    contract: 1,
    project: config.project,
    namespace: config.namespace,
    instance: config.instance,
    admin: config.admin,
    bucket: config.bucket,
    operationId,
    status: "running",
    stage: "reserved",
    createdAt: new Date(),
  });
  claimed = true;

  stage = "bucket_initialization";
  if (!bucketExists) {
    await storage.makeBucket(config.bucket, "us-east-1");
  }
  bucketExists = await storage.bucketExists(config.bucket);
  requireCondition(bucketExists, "bucket_confirmation_failed");

  // No public-read policy is created or changed.
  stage = "vector_initialization";
  if (!vector) {
    const response = await fetch(endpoint, {
      method: "PUT",
      redirect: "error",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        vectors: { dense: { size: 768, distance: "Cosine" } },
        sparse_vectors: { "text-sparse": {} },
      }),
      signal: AbortSignal.timeout(15000),
    });

    const ok = response.ok;
    await response.body?.cancel();
    requireCondition(ok, "vector_creation_not_confirmed");
  }

  vector = await readVector();
  verifyVector(vector);

  stage = "administrator_mapping";
  if (!account) {
    await accounts.insertOne({
      _id: config.admin,
      username: config.admin,
      googleUid: config.admin,
      googleProjectId: config.project,
      email: user.email,
      status: "active",
      roles: ["user", "admin"],
      provisionedBy: "explicit_customer_installation",
      installationOperationId: operationId,
      createdAt: new Date(),
    });
  }

  verifyAccount(
    await accounts.findOne({ _id: config.admin }),
    config,
    user.email,
  );

  stage = "completion_checkpoint";
  const completed = await receipts.updateOne(
    { _id: receiptId, operationId, status: "running" },
    { $set: { status: "complete", stage, completedAt: new Date() } },
  );
  requireCondition(completed.matchedCount === 1, "checkpoint_not_confirmed");

  claimed = false;
  console.log("PASS: administrator mapping, bucket and vector schema initialized.");
  console.log("No Google user/password change, credits or document grants.");
}

const deadline = setTimeout(() => {
  console.error("BOOTSTRAP FAILED:", stage, "deadline_exceeded");
  // Leave any running receipt for inspection; do not declare rollback.
  process.exit(1);
}, 1050000);

main()
  .then(() => {
    clearTimeout(deadline);
    return mongo?.close();
  })
  .then(() => process.exit(0))
  .catch(async (error) => {
    clearTimeout(deadline);

    if (claimed && receipts) {
      await receipts.updateOne(
        { _id: receiptId, operationId, status: "running" },
        { $set: {
          status: "needs_inspection",
          failureStage: stage,
          updatedAt: new Date(),
        } },
      ).catch(() => {});
    }

    const code =
      typeof error.code === "string" &&
      /^[A-Za-z0-9_./:-]{1,100}$/.test(error.code)
        ? error.code
        : "operation_failed";

    console.error("BOOTSTRAP FAILED:", stage, code);
    console.error("Do not delete accounts/storage or reclaim the receipt blindly.");
    await mongo?.close().catch(() => {});
    process.exit(1);
  });
