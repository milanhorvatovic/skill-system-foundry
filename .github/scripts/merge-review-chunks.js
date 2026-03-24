// Merge multiple Codex review chunk outputs into a single review-output.json.
//
// Reads .codex/chunks/chunk-*/review-output.json and produces .codex/review-output.json
// that the existing publish-review.js can consume without modification.
//
// Run: node .github/scripts/merge-review-chunks.js

const fs = require('node:fs');
const path = require('node:path');

const chunksDir = '.codex/chunks';
const outputFile = '.codex/review-output.json';

// Find review-output.json files only in expected artifact directories.
// Restricts to codex-review-chunk-* directories to avoid picking up
// stale or unrelated files from the prepare artifact.
function findReviewOutputs(dir) {
  const results = [];
  if (!fs.existsSync(dir)) return results;
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    if (!entry.isDirectory() || !entry.name.startsWith('codex-review-chunk-')) continue;
    const reviewFile = path.join(dir, entry.name, 'review-output.json');
    if (fs.existsSync(reviewFile)) {
      results.push(reviewFile);
    }
  }
  return results;
}

const reviewFiles = findReviewOutputs(chunksDir).sort();

if (reviewFiles.length === 0) {
  console.error('No review-output.json files found. Failing merge.');
  process.exit(1);
}

console.log(`Found ${reviewFiles.length} review output(s)...`);

const summaries = [];
const allChanges = [];
const allFiles = [];
const allFindings = [];
let model = '';
let worstVerdict = 'patch is correct';
let lowestConfidence = null;
let validChunks = 0;

for (const filePath of reviewFiles) {
  const label = path.relative(chunksDir, filePath);

  const raw = fs.readFileSync(filePath, 'utf8');
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    console.log(`  ${label}: invalid JSON — skipping`);
    continue;
  }

  // Shape validation: require core fields with correct types/values to prevent
  // partial/malformed chunks from biasing the merged verdict.
  const allowedVerdicts = ['patch is correct', 'patch is incorrect'];
  if (typeof parsed !== 'object' || parsed === null ||
      typeof parsed.summary !== 'string' || !Array.isArray(parsed.findings) ||
      !allowedVerdicts.includes(parsed.overall_correctness) ||
      !Number.isFinite(parsed.overall_confidence_score)) {
    console.log(`  ${label}: missing or invalid required fields — skipping`);
    continue;
  }

  validChunks += 1;
  console.log(`  ${label}: ${parsed.findings.length} finding(s)`);

  // Summary: collect non-empty summaries
  const summary = String(parsed.summary || '').trim();
  if (summary) {
    summaries.push(summary);
  }

  // Changes: append
  if (Array.isArray(parsed.changes)) {
    for (const c of parsed.changes) {
      const text = String(c).trim();
      if (text && !allChanges.includes(text)) {
        allChanges.push(text);
      }
    }
  }

  // Files: deduplicate by path, skip malformed entries
  if (Array.isArray(parsed.files)) {
    const existingPaths = new Set(allFiles.map(f => f.path));
    for (const f of parsed.files) {
      if (!f || typeof f !== 'object') continue;
      const filePath = typeof f.path === 'string' ? f.path : '';
      if (filePath && !existingPaths.has(filePath)) {
        allFiles.push({ path: filePath, description: typeof f.description === 'string' ? f.description : '' });
        existingPaths.add(filePath);
      }
    }
  }

  // Findings: append all (deduplication by signature happens in publish-review.js)
  if (Array.isArray(parsed.findings)) {
    allFindings.push(...parsed.findings);
  }

  // Model: take from first chunk that reports one
  if (!model && parsed.model) {
    model = String(parsed.model).trim();
  }

  // Verdict: most conservative wins (incorrect > correct)
  const verdict = String(parsed.overall_correctness || '').trim();
  if (verdict === 'patch is incorrect') {
    worstVerdict = 'patch is incorrect';
  }

  // Confidence: take the lowest finite value
  const conf = Number(parsed.overall_confidence_score);
  if (Number.isFinite(conf)) {
    lowestConfidence = lowestConfidence === null ? conf : Math.min(lowestConfidence, conf);
  }
}

// Guard: if no chunks were successfully parsed, fail so CI surfaces the issue.
if (validChunks === 0) {
  console.error('No valid chunk outputs found. Failing merge — no review will be published.');
  process.exit(1);
}

// Build merged output
const merged = {
  summary: summaries.join(' '),
  changes: allChanges,
  files: allFiles,
  findings: allFindings,
  overall_correctness: worstVerdict,
  overall_confidence_score: lowestConfidence !== null ? lowestConfidence : 0,
  model: model || 'unknown',
};

fs.writeFileSync(outputFile, JSON.stringify(merged, null, 2));
console.log(`Merged ${validChunks} chunk(s): ${allFindings.length} finding(s) -> ${outputFile}`);
