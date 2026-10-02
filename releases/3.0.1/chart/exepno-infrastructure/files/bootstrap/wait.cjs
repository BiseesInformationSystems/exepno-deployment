const { MongoClient } = require("/app/node_modules/mongodb");
const { configuration, receiptMatches } = require("./contract.cjs");

(async () => {
  const config = configuration(process.env);
  const mongo = new MongoClient(config.mongoUri, {
    maxPoolSize: 1,
    serverSelectionTimeoutMS: 3000,
    socketTimeoutMS: 5000,
  });

  const deadline = Date.now() + 1080000;

  try {
    while (Date.now() < deadline) {
      let receipt = null;

      try {
        await mongo.connect();
        receipt = await mongo.db("exepno").collection("exepno_installations")
          .findOne({ _id: config.receiptId });
      } catch {
        // Bounded wait for namespace-local database startup.
      }

      if (receipt) {
        if (!receiptMatches(receipt, config)) {
          throw new Error("installation_identity_conflict");
        }
        if (receipt.status === "needs_inspection") {
          throw new Error("bootstrap_requires_inspection");
        }
        if (receipt.status === "complete") {
          console.log("PASS: installation initialization confirmed.");
          return;
        }
      }

      await new Promise((resolve) => setTimeout(resolve, 5000));
    }

    throw new Error("bootstrap_wait_expired");
  } finally {
    await mongo.close().catch(() => {});
  }
})().then(() => process.exit(0)).catch(() => {
  console.error("Initialization gate failed. Inspect the bootstrap Job.");
  process.exit(1);
});
