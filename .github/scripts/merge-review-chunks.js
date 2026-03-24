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

// Discover chunk directories
const chunkDirs = fs.readdirSync(chunksDir, { withFileTypes: true })
  .filter(d => d.isDirectory() && d.name.startsWith('chunk-'))
  .map(d => d.name)
  .sort((a, b) => {
    const numA = Number(a.replace('chunk-', ''));
    const numB = Number(b.replace('chunk-', ''));
    return numA - numB;
  });

if (chunkDirs.length === 0) {
  console.log('No chunk directories found. Nothing to merge.');
  process.exit(0);
}

console.log(`Merging ${chunkDirs.length} chunk(s)...`);

const summaries = [];
const allChanges = [];
const allFiles = [];
const allFindings = [];
let model = '';
let worstVerdict = 'patch is correct';
let lowestConfidence = 1.0;

for (const dir of chunkDirs) {
  const filePath = path.join(chunksDir, dir, 'review-output.json');
  if (!fs.existsSync(filePath)) {
    console.log(`  ${dir}: no review-output.json — skipping`);
    continue;
  }

  const raw = fs.readFileSync(filePath, 'utf8');
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    console.log(`  ${dir}: invalid JSON — skipping`);
    continue;
  }

  console.log(`  ${dir}: ${(parsed.findings || []).length} finding(s)`);

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

  // Files: deduplicate by path
  if (Array.isArray(parsed.files)) {
    const existingPaths = new Set(allFiles.map(f => f.path));
    for (const f of parsed.files) {
      if (f.path && !existingPaths.has(f.path)) {
        allFiles.push(f);
        existingPaths.add(f.path);
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

  // Confidence: take the lowest
  const conf = Number(parsed.overall_confidence_score);
  if (Number.isFinite(conf) && conf < lowestConfidence) {
    lowestConfidence = conf;
  }
}

// Build merged output
const merged = {
  summary: summaries.join(' '),
  changes: allChanges,
  files: allFiles,
  findings: allFindings,
  overall_correctness: worstVerdict,
  overall_confidence_score: lowestConfidence,
  model: model || 'unknown',
};

fs.writeFileSync(outputFile, JSON.stringify(merged, null, 2));
console.log(`Merged output: ${allFindings.length} finding(s) -> ${outputFile}`);
