// Smoke test for merge-review-chunks.js
//
// Validates chunk discovery, shape validation, verdict aggregation,
// confidence handling, and expected chunk count enforcement.
// Run: node .github/scripts/test-merge-review-chunks.js

const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert');
const { execFileSync } = require('node:child_process');

const mergeScript = path.join(__dirname, 'merge-review-chunks.js');

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    passed += 1;
    console.log(`  PASS: ${name}`);
  } catch (err) {
    failed += 1;
    console.log(`  FAIL: ${name}`);
    console.log(`        ${err.message}`);
  }
}

function setupChunksDir() {
  const tmpDir = fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'merge-test-'));
  const chunksDir = path.join(tmpDir, '.codex', 'chunks');
  fs.mkdirSync(chunksDir, { recursive: true });
  return { tmpDir, chunksDir };
}

function writeChunk(chunksDir, chunkNum, data) {
  const dir = path.join(chunksDir, `codex-review-chunk-${chunkNum}`);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, 'review-output.json'), JSON.stringify(data));
}

function runMerge(tmpDir, env) {
  try {
    execFileSync('node', [mergeScript], {
      cwd: tmpDir,
      env: { ...process.env, ...env },
      stdio: 'pipe',
    });
    return { exitCode: 0, output: '' };
  } catch (err) {
    return { exitCode: err.status, output: err.stderr?.toString() || '' };
  }
}

function readMerged(tmpDir) {
  const file = path.join(tmpDir, '.codex', 'review-output.json');
  if (!fs.existsSync(file)) return null;
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

const validChunk = {
  summary: 'Test chunk.',
  changes: ['Change A'],
  files: [{ path: 'a.js', description: 'Changed A' }],
  findings: [{ title: 'Issue', priority: 1, confidence_score: 0.8, path: 'a.js', line: 1, start_line: null, body: 'Problem.', suggestion: null, reasoning: 'Saw issue.' }],
  overall_correctness: 'patch is correct',
  overall_confidence_score: 0.85,
  model: 'test-model',
};

const incorrectChunk = {
  ...validChunk,
  summary: 'Chunk with issues.',
  overall_correctness: 'patch is incorrect',
  overall_confidence_score: 0.7,
};

console.log('merge-review-chunks.js smoke tests\n');

// ── Valid single chunk ──────────────────────────────────────────────

test('merges a single valid chunk', () => {
  const { tmpDir, chunksDir } = setupChunksDir();
  writeChunk(chunksDir, 0, validChunk);
  const result = runMerge(tmpDir, {});
  assert.strictEqual(result.exitCode, 0);
  const merged = readMerged(tmpDir);
  assert.ok(merged);
  assert.strictEqual(merged.findings.length, 1);
  assert.strictEqual(merged.overall_correctness, 'patch is correct');
  assert.strictEqual(merged.model, 'test-model');
});

// ── Multiple chunks with conservative verdict ───────────────────────

test('takes most conservative verdict across chunks', () => {
  const { tmpDir, chunksDir } = setupChunksDir();
  writeChunk(chunksDir, 0, validChunk);
  writeChunk(chunksDir, 1, incorrectChunk);
  const result = runMerge(tmpDir, {});
  assert.strictEqual(result.exitCode, 0);
  const merged = readMerged(tmpDir);
  assert.strictEqual(merged.overall_correctness, 'patch is incorrect');
  assert.strictEqual(merged.overall_confidence_score, 0.7);
});

// ── Malformed chunk is skipped ──────────────────────────────────────

test('skips malformed chunk and still merges valid ones', () => {
  const { tmpDir, chunksDir } = setupChunksDir();
  writeChunk(chunksDir, 0, validChunk);
  writeChunk(chunksDir, 1, { broken: true });
  const result = runMerge(tmpDir, {});
  assert.strictEqual(result.exitCode, 0);
  const merged = readMerged(tmpDir);
  assert.strictEqual(merged.findings.length, 1);
});

// ── Zero valid chunks fails ─────────────────────────────────────────

test('fails when all chunks are invalid', () => {
  const { tmpDir, chunksDir } = setupChunksDir();
  writeChunk(chunksDir, 0, { broken: true });
  const result = runMerge(tmpDir, {});
  assert.strictEqual(result.exitCode, 1);
});

// ── No chunks directory fails ───────────────────────────────────────

test('fails when chunks directory does not exist', () => {
  const tmpDir = fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'merge-test-'));
  const result = runMerge(tmpDir, {});
  assert.strictEqual(result.exitCode, 1);
});

// ── Expected chunk count enforcement ────────────────────────────────

test('fails when valid chunks < expected count', () => {
  const { tmpDir, chunksDir } = setupChunksDir();
  writeChunk(chunksDir, 0, validChunk);
  const result = runMerge(tmpDir, { EXPECTED_CHUNKS: '3' });
  assert.strictEqual(result.exitCode, 1);
});

test('succeeds when valid chunks == expected count', () => {
  const { tmpDir, chunksDir } = setupChunksDir();
  writeChunk(chunksDir, 0, validChunk);
  writeChunk(chunksDir, 1, incorrectChunk);
  const result = runMerge(tmpDir, { EXPECTED_CHUNKS: '2' });
  assert.strictEqual(result.exitCode, 0);
});

test('fails when valid chunks > expected count', () => {
  const { tmpDir, chunksDir } = setupChunksDir();
  writeChunk(chunksDir, 0, validChunk);
  writeChunk(chunksDir, 1, incorrectChunk);
  writeChunk(chunksDir, 2, validChunk);
  const result = runMerge(tmpDir, { EXPECTED_CHUNKS: '2' });
  assert.strictEqual(result.exitCode, 1);
});

test('fails when EXPECTED_CHUNKS is non-numeric', () => {
  const { tmpDir, chunksDir } = setupChunksDir();
  writeChunk(chunksDir, 0, validChunk);
  const result = runMerge(tmpDir, { EXPECTED_CHUNKS: 'two' });
  assert.strictEqual(result.exitCode, 1);
});

// ── Files deduplication ─────────────────────────────────────────────

test('deduplicates files across chunks', () => {
  const { tmpDir, chunksDir } = setupChunksDir();
  writeChunk(chunksDir, 0, validChunk);
  writeChunk(chunksDir, 1, { ...validChunk, files: [{ path: 'a.js', description: 'Duplicate' }, { path: 'b.js', description: 'New' }] });
  const result = runMerge(tmpDir, {});
  assert.strictEqual(result.exitCode, 0);
  const merged = readMerged(tmpDir);
  assert.strictEqual(merged.files.length, 2);
});

// ── Malformed files entries don't crash ──────────────────────────────

test('handles null entries in files array', () => {
  const { tmpDir, chunksDir } = setupChunksDir();
  writeChunk(chunksDir, 0, { ...validChunk, files: [null, { path: 'a.js', description: 'OK' }] });
  const result = runMerge(tmpDir, {});
  assert.strictEqual(result.exitCode, 0);
  const merged = readMerged(tmpDir);
  assert.strictEqual(merged.files.length, 1);
});

// ── Nested artifact paths ────────────────────────────────────────────

function writeNestedChunk(chunksDir, chunkNum, data) {
  // Simulate GitHub's nested artifact extraction layout:
  // codex-review-chunk-N/.codex/chunks/chunk-N/review-output.json
  const dir = path.join(chunksDir, `codex-review-chunk-${chunkNum}`, '.codex', 'chunks', `chunk-${chunkNum}`);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, 'review-output.json'), JSON.stringify(data));
}

test('discovers review-output.json in nested artifact paths', () => {
  const { tmpDir, chunksDir } = setupChunksDir();
  writeNestedChunk(chunksDir, 0, validChunk);
  const result = runMerge(tmpDir, {});
  assert.strictEqual(result.exitCode, 0);
  const merged = readMerged(tmpDir);
  assert.ok(merged);
  assert.strictEqual(merged.findings.length, 1);
});

test('discovers mix of flat and nested artifact paths', () => {
  const { tmpDir, chunksDir } = setupChunksDir();
  writeChunk(chunksDir, 0, validChunk);
  writeNestedChunk(chunksDir, 1, incorrectChunk);
  const result = runMerge(tmpDir, {});
  assert.strictEqual(result.exitCode, 0);
  const merged = readMerged(tmpDir);
  assert.strictEqual(merged.overall_correctness, 'patch is incorrect');
});

// ── Nested chunk ordering ─────────────────────────────────────────────

test('nested chunks sort numerically (chunk-2 before chunk-10)', () => {
  const { tmpDir, chunksDir } = setupChunksDir();
  const chunk2 = { ...validChunk, summary: 'chunk2-summary' };
  const chunk10 = { ...validChunk, summary: 'chunk10-summary' };
  writeNestedChunk(chunksDir, 2, chunk2);
  writeNestedChunk(chunksDir, 10, chunk10);
  const result = runMerge(tmpDir, {});
  assert.strictEqual(result.exitCode, 0);
  const merged = readMerged(tmpDir);
  assert.ok(merged.summary.indexOf('chunk2-summary') < merged.summary.indexOf('chunk10-summary'),
    `Expected chunk2 summary before chunk10 summary, got: "${merged.summary}"`);
});

// ── Flat extraction fallback (download-artifact@v8 single match) ───────

function writeFlatChunk(chunksDir, data) {
  // Simulate download-artifact@v8 behavior when pattern matches exactly
  // one artifact: the file is extracted directly into the path without
  // creating a per-artifact subdirectory.
  fs.writeFileSync(path.join(chunksDir, 'review-output.json'), JSON.stringify(data));
}

test('discovers review-output.json in flat extraction layout', () => {
  const { tmpDir, chunksDir } = setupChunksDir();
  writeFlatChunk(chunksDir, validChunk);
  const result = runMerge(tmpDir, { EXPECTED_CHUNKS: '1' });
  assert.strictEqual(result.exitCode, 0);
  const merged = readMerged(tmpDir);
  assert.ok(merged);
  assert.strictEqual(merged.findings.length, 1);
});

test('prefers subdirectory layout over flat file', () => {
  const { tmpDir, chunksDir } = setupChunksDir();
  writeChunk(chunksDir, 0, validChunk);
  // Also place a stale flat file — should be ignored
  fs.writeFileSync(path.join(chunksDir, 'review-output.json'), '{"broken": true}');
  const result = runMerge(tmpDir, { EXPECTED_CHUNKS: '1' });
  assert.strictEqual(result.exitCode, 0);
  const merged = readMerged(tmpDir);
  assert.strictEqual(merged.findings.length, 1);
  assert.strictEqual(merged.overall_correctness, 'patch is correct');
});

// ── Summary ─────────────────────────────────────────────────────────

console.log(`\n${passed} passed, ${failed} failed\n`);
if (failed > 0) {
  process.exit(1);
}
