function requireCondition(condition, code) {
  if (!condition) {
    const error = new Error(code);
    error.code = code;
    throw error;
  }
}

function configuration(env) {
  const project = env.EXEPNO_CUSTOMER_PROJECT;
  const instance = env.EXEPNO_INSTANCE;
  const namespace = env.EXEPNO_NAMESPACE;
  const admin = env.EXEPNO_INITIAL_ADMIN_UID;

  requireCondition(
    typeof project === "string" &&
    /^[a-z][a-z0-9-]{4,28}[a-z0-9]$/.test(project),
    "invalid_customer_project",
  );
  requireCondition(
    typeof instance === "string" &&
    /^[a-z][a-z0-9-]{0,38}[a-z0-9]$/.test(instance),
    "invalid_instance",
  );
  requireCondition(
    typeof namespace === "string" &&
    /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(namespace),
    "invalid_namespace",
  );
  requireCondition(
    typeof admin === "string" &&
    /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(admin),
    "invalid_administrator_uid",
  );

  requireCondition(
    env.NOETIC_AUTH_PROJECT_ID === project &&
    env.GOOGLE_CLOUD_PROJECT === project,
    "authentication_project_mismatch",
  );

  requireCondition(
    !env.GOOGLE_APPLICATION_CREDENTIALS,
    "credential_file_override_not_allowed",
  );

  const mongoHost = `${instance}-mongodb`;
  let uri;
  try {
    uri = new URL(env.MONGODB_URI);
  } catch {
    requireCondition(false, "invalid_mongodb_uri");
  }

  requireCondition(
    uri.protocol === "mongodb:" &&
    uri.hostname === mongoHost &&
    uri.port === "27017" &&
    uri.pathname === "/exepno" &&
    uri.username === "exepno" &&
    Boolean(uri.password) &&
    uri.searchParams.get("authSource") === "exepno" &&
    [...uri.searchParams.keys()].every((key) => key === "authSource") &&
    !uri.hash,
    "mongodb_must_be_installation_local",
  );

  let password;
  try {
    password = decodeURIComponent(uri.password);
  } catch {
    requireCondition(false, "invalid_mongodb_password_encoding");
  }

  requireCondition(
    typeof env.EXEPNO_MONGO_APP_PASSWORD === "string" &&
    env.EXEPNO_MONGO_APP_PASSWORD.length > 0 &&
    password === env.EXEPNO_MONGO_APP_PASSWORD,
    "mongo_password_configuration_mismatch",
  );

  requireCondition(
    env.MINIO_ENDPOINT === `${instance}-minio` &&
    env.MINIO_PORT === "9000" &&
    env.MINIO_USE_SSL === "false" &&
    env.QDRANT_HOST === `${instance}-qdrant` &&
    env.QDRANT_PORT === "6333",
    "data_services_must_be_installation_local",
  );

  const bucket = env.MINIO_BUCKET_NAME;
  requireCondition(
    typeof bucket === "string" &&
    /^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$/.test(bucket) &&
    !bucket.includes(".."),
    "invalid_bucket",
  );

  requireCondition(
    Boolean(env.MINIO_ACCESS_KEY) &&
    Boolean(env.MINIO_SECRET_KEY),
    "missing_storage_credentials",
  );

  const match =
    /^projects\/([A-Za-z0-9:._-]+)\/secrets\/([A-Za-z0-9_-]+)\/versions\/([1-9][0-9]*)$/
      .exec(env.NOETIC_SECRET_VERSION || "");

  requireCondition(Boolean(match), "numeric_provider_secret_version_required");

  return {
    project,
    instance,
    namespace,
    admin,
    bucket,
    secretProject: match[1],
    mongoUri: env.MONGODB_URI,
    minioHost: env.MINIO_ENDPOINT,
    qdrantHost: env.QDRANT_HOST,
    receiptId: `installation:${namespace}:${instance}`,
  };
}

function verifyProject(config, metadataProject, metadataNumber) {
  requireCondition(
    config.project === metadataProject,
    "workload_project_mismatch",
  );
  requireCondition(
    config.secretProject === metadataProject ||
    config.secretProject === metadataNumber,
    "provider_secret_project_mismatch",
  );
}

function verifyAccount(account, config, email) {
  if (!account) return;

  requireCondition(
    account._id === config.admin &&
    account.username === config.admin &&
    account.googleUid === config.admin &&
    account.googleProjectId === config.project &&
    account.email === email &&
    account.status === "active" &&
    Array.isArray(account.roles) &&
    account.roles.includes("admin"),
    "existing_account_requires_operator_review",
  );
}

function verifyVector(document) {
  const params = document?.result?.config?.params;
  requireCondition(
    params?.vectors?.dense?.size === 768 &&
    params?.vectors?.dense?.distance === "Cosine" &&
    Object.prototype.hasOwnProperty.call(
      params?.sparse_vectors || {}, "text-sparse",
    ),
    "vector_schema_mismatch",
  );
}

function receiptMatches(receipt, config) {
  return Boolean(
    receipt &&
    receipt.contract === 1 &&
    receipt.project === config.project &&
    receipt.namespace === config.namespace &&
    receipt.instance === config.instance &&
    receipt.admin === config.admin &&
    receipt.bucket === config.bucket
  );
}

module.exports = {
  configuration,
  verifyProject,
  verifyAccount,
  verifyVector,
  receiptMatches,
  requireCondition,
};
