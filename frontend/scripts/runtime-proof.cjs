"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const proofPath = process.env.SPYBOXD_RUNTIME_PROOF_FILE;

if (proofPath) {
  const frontendRoot = fs.realpathSync(process.cwd());
  const releaseRoot = fs.realpathSync(path.join(frontendRoot, ".."));
  const runtimePath = fs.realpathSync(process.execPath);
  const expectedNextEntrypoint = fs.realpathSync(
    path.join(frontendRoot, "node_modules", "next", "dist", "bin", "next"),
  );
  const nextEntrypoint = fs.realpathSync(process.argv[1]);
  if (nextEntrypoint !== expectedNextEntrypoint) {
    throw new Error("The production frontend entrypoint is invalid");
  }
  const revision = fs
    .readFileSync(path.join(releaseRoot, "REVISION"), "utf8")
    .trim();

  if (!/^[0-9a-f]{40}$/.test(revision)) {
    throw new Error("The production release revision is invalid");
  }

  const runtimeHash = crypto.createHash("sha256");
  const runtimeFd = fs.openSync(runtimePath, fs.constants.O_RDONLY);
  const buffer = Buffer.allocUnsafe(1024 * 1024);
  try {
    for (;;) {
      const bytesRead = fs.readSync(runtimeFd, buffer, 0, buffer.length, null);
      if (bytesRead === 0) break;
      runtimeHash.update(buffer.subarray(0, bytesRead));
    }
  } finally {
    fs.closeSync(runtimeFd);
  }

  const statText = fs.readFileSync("/proc/self/stat", "utf8").trim();
  const commandEnd = statText.lastIndexOf(")");
  const statFields = statText.slice(commandEnd + 2).split(/\s+/);
  const startTicks = statFields[19];
  if (commandEnd < 0 || !/^\d+$/.test(startTicks || "")) {
    throw new Error("Could not determine the frontend process start time");
  }

  const payload = {
    format_version: 1,
    revision,
    runtime_path: runtimePath,
    node_sha256: runtimeHash.digest("hex"),
    node_version: process.version,
    pid: process.pid,
    start_ticks: startTicks,
    boot_id: fs.readFileSync("/proc/sys/kernel/random/boot_id", "utf8").trim(),
    next_entrypoint: nextEntrypoint,
  };

  const proofDirectory = path.dirname(proofPath);
  const resolvedProofDirectory = fs.realpathSync(proofDirectory);
  if (resolvedProofDirectory !== "/var/cache/spyboxd-frontend") {
    throw new Error("The production runtime proof path is outside its private cache");
  }

  const temporaryPath = path.join(
    resolvedProofDirectory,
    `.runtime-proof.${process.pid}.${crypto.randomBytes(8).toString("hex")}`,
  );
  const proofFd = fs.openSync(
    temporaryPath,
    fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_WRONLY,
    0o640,
  );
  try {
    fs.writeFileSync(proofFd, `${JSON.stringify(payload)}\n`, "utf8");
    fs.fsyncSync(proofFd);
  } finally {
    fs.closeSync(proofFd);
  }
  fs.chmodSync(temporaryPath, 0o640);
  fs.renameSync(temporaryPath, proofPath);
}
