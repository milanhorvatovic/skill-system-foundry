// Smoke test for publish-review.js
//
// Validates formatting, filtering, sorting, and mapping logic using fixtures.
// Run: node .github/scripts/test-publish-review.js

const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert');

// ── Fixtures ────────────────────────────────────────────────────────────

const reviewOutput = {
  summary: 'Test PR summary for smoke test.',
  changes: ['Added feature X', 'Fixed bug Y'],
  files: [
    { path: 'src/main.js', description: 'Added feature X' },
    { path: 'src/utils.js', description: 'Fixed bug Y' },
  ],
  findings: [
    {
      title: 'P2 style issue',
      priority: 2,
      confidence_score: 0.8,
      path: 'src/main.js',
      line: 5,
      body: 'Consider renaming for clarity.',
    },
    {
      title: 'P0 critical bug',
      priority: 0,
      confidence_score: 0.95,
      path: 'src/main.js',
      line: 10,
      body: 'This will crash at runtime.',
      suggestion: 'fixedCode();',
    },
    {
      title: 'P1 correctness issue',
      priority: 1,
      confidence_score: 0.85,
      path: 'src/utils.js',
      line: 3,
      body: 'Off-by-one error in loop.',
    },
    {
      title: 'P3 minor nit',
      priority: 3,
      confidence_score: 0.6,
      path: 'src/utils.js',
      line: 7,
      body: 'Whitespace inconsistency.',
    },
    {
      title: 'Low confidence finding',
      priority: 2,
      confidence_score: 0.1,
      path: 'src/main.js',
      line: 15,
      body: 'Might be an issue.',
    },
    {
      // Incomplete finding — missing body
      title: 'Incomplete finding',
      priority: 1,
      confidence_score: 0.9,
      path: 'src/main.js',
      line: 20,
      body: '',
    },
    {
      title: 'Not on changed line',
      priority: 1,
      confidence_score: 0.9,
      path: 'src/main.js',
      line: 999,
      body: 'This line was not changed.',
    },
  ],
  overall_correctness: 'patch is correct',
  overall_confidence_score: 0.92,
  model: 'o3-2025-04-16',
};

const prDiff = `diff --git a/src/main.js b/src/main.js
--- a/src/main.js
+++ b/src/main.js
@@ -1,3 +1,20 @@
+line1
+line2
+line3
+line4
+line5
+line6
+line7
+line8
+line9
+line10
+line11
+line12
+line13
+line14
+line15
+line16
+line17
+line18
+line19
+line20
diff --git a/src/utils.js b/src/utils.js
--- a/src/utils.js
+++ b/src/utils.js
@@ -1,1 +1,10 @@
+line1
+line2
+line3
+line4
+line5
+line6
+line7
+line8
+line9
+line10
`;

// ── Setup ───────────────────────────────────────────────────────────────

const tmpDir = fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'codex-test-'));
const codexDir = path.join(tmpDir, '.codex');
const scriptsDir = path.join(codexDir, 'scripts');
fs.mkdirSync(scriptsDir, { recursive: true });

fs.writeFileSync(path.join(codexDir, 'review-output.json'), JSON.stringify(reviewOutput));
fs.writeFileSync(path.join(codexDir, 'pr.diff'), prDiff);

// Copy the publish script to the expected location
fs.copyFileSync(
  path.join(__dirname, 'publish-review.js'),
  path.join(scriptsDir, 'publish-review.js'),
);

// ── Mock GitHub API ─────────────────────────────────────────────────────

let capturedReview = null;

const mockGithub = {
  paginate: async (method) => {
    // Return empty arrays for both listReviewComments and listReviews
    return [];
  },
  rest: {
    pulls: {
      listReviewComments: 'listReviewComments',
      listReviews: 'listReviews',
      createReview: async (payload) => {
        capturedReview = payload;
      },
    },
  },
};

const mockContext = {
  payload: {
    pull_request: {
      number: 42,
      head: { sha: 'abc123' },
    },
  },
  repo: { owner: 'test-owner', repo: 'test-repo' },
};

const mockCore = {
  warning: () => {},
};

// ── Test runner ─────────────────────────────────────────────────────────

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

async function runTests() {
  console.log('publish-review.js smoke tests\n');

  // ── Run the publish function ──────────────────────────────────────

  // Set environment
  const originalCwd = process.cwd();
  process.chdir(tmpDir);

  process.env.RUN_URL = 'https://github.com/test/actions/runs/1';
  process.env.MAX_INLINE_CONVERSATIONS = '20';
  process.env.MAX_SUMMARY_CHARS = '4000';
  process.env.MAX_CHANGE_ITEMS = '50';
  process.env.MAX_FILES_IN_TABLE = '100';
  process.env.MAX_REVIEW_BODY_CHARS = '60000';
  process.env.GITHUB_MAX_BODY_CHARS = '65536';
  process.env.CODEX_REVIEW_MODEL = 'test-model-configured';
  process.env.MIN_CONFIDENCE = '0.5';

  const publish = require(path.join(scriptsDir, 'publish-review.js'));
  await publish({ github: mockGithub, context: mockContext, core: mockCore, process });

  process.chdir(originalCwd);

  // ── Assertions ────────────────────────────────────────────────────

  test('review was created', () => {
    assert.ok(capturedReview, 'Expected createReview to be called');
  });

  test('review has inline comments', () => {
    assert.ok(capturedReview.comments, 'Expected comments array');
    assert.ok(capturedReview.comments.length > 0, 'Expected at least one comment');
  });

  // Priority sorting: P0 should come before P1, P1 before P2, etc.
  test('findings are sorted by priority (P0 first)', () => {
    const comments = capturedReview.comments;
    const priorities = comments.map(c => {
      if (c.body.includes('CAUTION')) return 0;
      if (c.body.includes('WARNING')) return 1;
      if (c.body.includes('NOTE')) return 2; // P2 or P3
      return 99;
    });
    for (let i = 1; i < priorities.length; i++) {
      assert.ok(priorities[i] >= priorities[i - 1],
        `Comment ${i} priority ${priorities[i]} should be >= comment ${i - 1} priority ${priorities[i - 1]}`);
    }
  });

  // Priority-to-alert mapping
  test('P0 maps to CAUTION', () => {
    const p0Comment = capturedReview.comments.find(c => c.body.includes('P0 critical bug'));
    assert.ok(p0Comment, 'Expected P0 finding');
    assert.ok(p0Comment.body.includes('[!CAUTION]'), 'P0 should use CAUTION alert');
  });

  test('P1 maps to WARNING', () => {
    const p1Comment = capturedReview.comments.find(c => c.body.includes('P1 correctness issue'));
    assert.ok(p1Comment, 'Expected P1 finding');
    assert.ok(p1Comment.body.includes('[!WARNING]'), 'P1 should use WARNING alert');
  });

  test('P2 maps to NOTE', () => {
    const p2Comment = capturedReview.comments.find(c => c.body.includes('P2 style issue'));
    assert.ok(p2Comment, 'Expected P2 finding');
    assert.ok(p2Comment.body.includes('[!NOTE]'), 'P2 should use NOTE alert');
  });

  test('P3 maps to NOTE', () => {
    const p3Comment = capturedReview.comments.find(c => c.body.includes('P3 minor nit'));
    assert.ok(p3Comment, 'Expected P3 finding');
    assert.ok(p3Comment.body.includes('[!NOTE]'), 'P3 should use NOTE alert');
  });

  // Model resolution: configured env var takes precedence
  test('model resolution prefers configured over self-reported', () => {
    assert.ok(capturedReview.body.includes('test-model-configured'),
      'Footer should use configured model name');
    assert.ok(!capturedReview.body.includes('o3-2025-04-16'),
      'Footer should not use self-reported model when configured is set');
  });

  // Verdict display
  test('verdict appears in review body', () => {
    assert.ok(capturedReview.body.includes('Verdict:'), 'Expected verdict in body');
    assert.ok(capturedReview.body.includes('Patch is correct'), 'Expected correctness value');
    assert.ok(capturedReview.body.includes('0.92'), 'Expected confidence score');
  });

  // Confidence filtering: MIN_CONFIDENCE=0.5 should skip the 0.1 finding
  test('low confidence findings are skipped', () => {
    const lowConfComment = capturedReview.comments.find(c => c.body.includes('Might be an issue'));
    assert.ok(!lowConfComment, 'Finding with confidence 0.1 should be skipped when MIN_CONFIDENCE=0.5');
  });

  // Incomplete findings are skipped (empty body)
  test('incomplete findings are skipped', () => {
    const incompleteComment = capturedReview.comments.find(c => c.body.includes('Incomplete finding'));
    assert.ok(!incompleteComment, 'Finding with empty body should be skipped');
  });

  // Findings on non-changed lines are skipped
  test('findings on non-changed lines are skipped', () => {
    const offLineComment = capturedReview.comments.find(c => c.body.includes('Not on changed line'));
    assert.ok(!offLineComment, 'Finding on line 999 should be skipped');
  });

  // Suggestion block
  test('P0 finding includes suggestion block', () => {
    const p0Comment = capturedReview.comments.find(c => c.body.includes('P0 critical bug'));
    assert.ok(p0Comment.body.includes('```suggestion'), 'Expected suggestion block');
    assert.ok(p0Comment.body.includes('fixedCode();'), 'Expected suggestion content');
  });

  // body field is used (not comment)
  test('finding body field is used in comment', () => {
    const p1Comment = capturedReview.comments.find(c => c.body.includes('P1 correctness issue'));
    assert.ok(p1Comment.body.includes('Off-by-one error in loop'), 'Expected body content');
  });

  // Metadata section mentions skipped low-confidence
  test('metadata mentions skipped low-confidence findings', () => {
    assert.ok(capturedReview.body.includes('below confidence threshold'),
      'Expected low-confidence skip note in metadata');
  });

  // ── Model fallback test ───────────────────────────────────────────

  // Test self-reported fallback
  capturedReview = null;
  delete process.env.CODEX_REVIEW_MODEL;
  process.env.MIN_CONFIDENCE = '0';

  process.chdir(tmpDir);
  await publish({ github: mockGithub, context: mockContext, core: mockCore, process });
  process.chdir(originalCwd);

  test('model falls back to self-reported when env var is empty', () => {
    assert.ok(capturedReview.body.includes('o3-2025-04-16'),
      'Footer should use self-reported model when CODEX_REVIEW_MODEL is not set');
  });

  // ── Summary ───────────────────────────────────────────────────────

  console.log(`\n${passed} passed, ${failed} failed\n`);
  if (failed > 0) {
    process.exit(1);
  }
}

runTests().catch((err) => {
  console.error('Test execution failed:', err);
  process.exit(1);
});
