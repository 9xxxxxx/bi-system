import { createHash } from "node:crypto";
import { readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve } from "node:path";
import { gzipSync, brotliCompressSync, constants as zlibConstants } from "node:zlib";

const scriptsDir = dirname(fileURLToPath(import.meta.url));
const frontendDir = resolve(scriptsDir, "..");
const repositoryDir = resolve(frontendDir, "..", "..", "..");
const verificationDir = join(repositoryDir, "docs", "verification");
const lockPath = join(frontendDir, "package-lock.json");
const lock = JSON.parse(readFileSync(lockPath, "utf8"));
const rootDependencies = lock.packages[""].dependencies ?? {};
const compatibleLicenses = new Set(["0BSD", "Apache-2.0", "BSD-3-Clause", "ISC", "MIT"]);

function csvCell(value) {
  const text = String(value ?? "");
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function packageLicenseRows() {
  return Object.entries(lock.packages)
    .filter(([location, metadata]) => location !== "" && metadata.dev !== true)
    .map(([location, metadata]) => {
      const packageDir = join(frontendDir, ...location.split("/"));
      const packageJson = JSON.parse(readFileSync(join(packageDir, "package.json"), "utf8"));
      const evidenceFiles = readdirSync(packageDir)
        .filter((name) => /^(licen[cs]e|notice|copyright)([.-]|$)/i.test(name))
        .sort();
      const license = typeof packageJson.license === "string" ? packageJson.license : metadata.license;
      return {
        package: packageJson.name,
        version: packageJson.version,
        relationship: Object.hasOwn(rootDependencies, packageJson.name) ? "direct" : "transitive",
        license,
        evidence_files: evidenceFiles.length > 0 ? evidenceFiles.join(";") : "package.json only",
        commercial_compatibility: compatibleLicenses.has(license) ? "compatible" : "review_required",
        lock_path: location.replaceAll("\\", "/"),
      };
    })
    .sort((left, right) =>
      left.relationship.localeCompare(right.relationship) ||
      left.package.localeCompare(right.package) ||
      left.lock_path.localeCompare(right.lock_path),
    );
}

function writeLicenseEvidence(rows) {
  const columns = [
    "package",
    "version",
    "relationship",
    "license",
    "evidence_files",
    "commercial_compatibility",
    "lock_path",
  ];
  const csv = [
    columns.join(","),
    ...rows.map((row) => columns.map((column) => csvCell(row[column])).join(",")),
  ].join("\n") + "\n";
  writeFileSync(join(verificationDir, "licenses-m3.csv"), csv, "utf8");
}

function compressedSizes(filePath) {
  const content = readFileSync(filePath);
  return {
    raw_bytes: content.length,
    gzip_bytes: gzipSync(content, { level: 9 }).length,
    brotli_bytes: brotliCompressSync(content, {
      params: { [zlibConstants.BROTLI_PARAM_QUALITY]: 11 },
    }).length,
  };
}

function sumSizes(chunks) {
  return chunks.reduce(
    (totals, chunk) => ({
      raw_bytes: totals.raw_bytes + chunk.raw_bytes,
      gzip_bytes: totals.gzip_bytes + chunk.gzip_bytes,
      brotli_bytes: totals.brotli_bytes + chunk.brotli_bytes,
    }),
    { raw_bytes: 0, gzip_bytes: 0, brotli_bytes: 0 },
  );
}

function buildEvidence(distName) {
  const distDir = join(frontendDir, distName);
  const manifest = JSON.parse(readFileSync(join(distDir, ".vite", "manifest.json"), "utf8"));
  const entryKey = Object.keys(manifest).find((key) => manifest[key].isEntry);
  if (entryKey === undefined) throw new Error(`No entry found in ${distName} manifest`);

  const initialFiles = new Set();
  const visit = (key) => {
    const item = manifest[key];
    if (item === undefined) throw new Error(`Unknown manifest key ${key}`);
    initialFiles.add(item.file);
    for (const css of item.css ?? []) initialFiles.add(css);
    for (const imported of item.imports ?? []) visit(imported);
  };
  visit(entryKey);

  const assetDir = join(distDir, "assets");
  const chunks = readdirSync(assetDir)
    .filter((name) => /\.(css|js)$/.test(name))
    .map((name) => {
      const file = `assets/${name}`;
      const group = name.startsWith("echarts-")
        ? "echarts"
        : name.startsWith("layout-")
          ? "react-grid-layout"
          : name.startsWith("GridStackCandidate-")
            ? "gridstack-lazy"
            : "application";
      return { file, group, initial: initialFiles.has(file), ...compressedSizes(join(assetDir, name)) };
    })
    .sort((left, right) => left.file.localeCompare(right.file));

  return {
    entry: entryKey,
    initial: sumSizes(chunks.filter((chunk) => chunk.initial)),
    lazy: sumSizes(chunks.filter((chunk) => !chunk.initial)),
    total: sumSizes(chunks),
    chunks,
  };
}

function subtractSizes(full, baseline) {
  return {
    raw_bytes: full.raw_bytes - baseline.raw_bytes,
    gzip_bytes: full.gzip_bytes - baseline.gzip_bytes,
    brotli_bytes: full.brotli_bytes - baseline.brotli_bytes,
  };
}

function writeBundleEvidence(licenseRows) {
  const baseline = buildEvidence("dist-baseline");
  const candidate = buildEvidence("dist");
  const echartsInInitialClosure = candidate.chunks.some(
    (chunk) => chunk.group === "echarts" && chunk.initial,
  );
  const npmUserAgent = process.env.npm_config_user_agent ?? "unknown";
  const evidence = {
    schema_version: 1,
    generated_at: new Date().toISOString(),
    environment: {
      node: process.version,
      npm: npmUserAgent.match(/npm\/([^ ]+)/)?.[1] ?? "unknown",
      platform: process.platform,
      architecture: process.arch,
      vite: lock.packages["node_modules/vite"].version,
    },
    inputs: {
      baseline: "baseline.html using React 19, React DOM, Lucide, shared CSS and the same Vite config",
      candidate: "index.html with ECharts, React Grid Layout and lazy GridStack comparison",
      package_lock_sha256: createHash("sha256").update(readFileSync(lockPath)).digest("hex"),
    },
    baseline,
    candidate,
    initial_delta: subtractSizes(candidate.initial, baseline.initial),
    dependency_licenses: {
      production_package_count: licenseRows.length,
      identifiers: [...new Set(licenseRows.map((row) => row.license))].sort(),
      review_required: licenseRows.filter((row) => row.commercial_compatibility !== "compatible").length,
    },
    decision: {
      echarts_initial_load: echartsInInitialClosure ? "rejected" : "deferred",
      reason: echartsInInitialClosure
        ? "The ECharts chunk exceeds the 500 kB raw Vite warning threshold and is part of the initial closure."
        : "The ECharts chunk is isolated behind a dynamic import and is absent from the initial manifest closure.",
      required_production_action: echartsInInitialClosure
        ? "Dynamically load the dashboard chart route/adapter and rerun this evidence against the production entry before dependency approval."
        : "Preserve the dynamic chart boundary when integrating the production dashboard and rerun bundle evidence against that entry.",
      preferred_layout: "react-grid-layout@2.2.3",
      fallback_layout: "gridstack@12.6.0 remains spike-only and lazy-loaded",
    },
  };
  writeFileSync(join(verificationDir, "bundle-m3.json"), JSON.stringify(evidence, null, 2) + "\n", "utf8");
}

const licenseRows = packageLicenseRows();
writeLicenseEvidence(licenseRows);
writeBundleEvidence(licenseRows);
console.log(`wrote ${licenseRows.length} license rows and bundle evidence`);
