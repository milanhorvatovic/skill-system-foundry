// Publish Codex PR review as GitHub pull request review with inline comments.
//
// Called from the codex-code-review workflow via actions/github-script.
// Reads .codex/review-output.json and .codex/pr.diff, then posts a structured
// review with inline findings. Uses 3-tier JSON parsing with graceful fallback
// when Codex returns non-JSON output.

const fs = require('node:fs');
const crypto = require('node:crypto');

// ── JSON parsing (3-tier fallback) ──────────────────────────────────

function tryParseJson(text) {
  try { return JSON.parse(text); } catch { return null; }
}

// Accept only review-shaped objects: must be a non-null, non-array object
// with at least a `findings` array. This prevents `[]`, `{}`, or other
// valid-but-useless JSON from suppressing the fallback display.
function isReviewShaped(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value) &&
    Array.isArray(value.findings);
}

function parseStructuredReview(raw) {
  const trimmed = raw.trim();

  // Strategy 1: Raw JSON
  let parsed = tryParseJson(trimmed);
  if (isReviewShaped(parsed)) return parsed;

  // Strategy 2: Fenced code block (```json ... ```)
  const fenced = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fenced) {
    parsed = tryParseJson(fenced[1].trim());
    if (isReviewShaped(parsed)) return parsed;
  }

  // Strategy 3: Brace extraction (first { ... last })
  const firstBrace = trimmed.indexOf('{');
  const lastBrace = trimmed.lastIndexOf('}');
  if (firstBrace !== -1 && lastBrace > firstBrace) {
    parsed = tryParseJson(trimmed.slice(firstBrace, lastBrace + 1));
    if (isReviewShaped(parsed)) return parsed;
  }

  return null;
}

function parseAddedLinesByFile(diffText) {
  const addedByFile = new Map();
  let currentFile = null;
  let newLine = null;

  for (const rawLine of diffText.split('\n')) {
    const line = rawLine.replace(/\r$/, '');

    if (line.startsWith('diff --git ')) {
      currentFile = null;
      newLine = null;
      continue;
    }

    // Only treat +++ as a file header before the first hunk.
    // Inside a hunk (newLine != null), +++ is a content line.
    if (line.startsWith('+++ ') && newLine == null) {
      const nextPath = line.slice(4).trim();
      if (nextPath === '/dev/null') {
        currentFile = null;
        continue;
      }
      currentFile = nextPath.startsWith('b/') ? nextPath.slice(2) : nextPath;
      if (!addedByFile.has(currentFile)) {
        addedByFile.set(currentFile, new Set());
      }
      continue;
    }

    const hunkMatch = line.match(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    if (hunkMatch) {
      newLine = Number(hunkMatch[1]);
      continue;
    }

    if (!currentFile || newLine == null) {
      continue;
    }

    if (line.startsWith('+')) {
      addedByFile.get(currentFile).add(newLine);
      newLine += 1;
      continue;
    }

    if (line.startsWith('-')) {
      continue;
    }

    if (line.startsWith(' ')) {
      newLine += 1;
      continue;
    }
  }

  return addedByFile;
}

function normalizePath(pathValue) {
  return String(pathValue || '')
    .trim()
    .replace(/^`+|`+$/g, '')
    .replace(/^\.\/+/, '')
    .replace(/^(?:a|b)\//, '');
}

function escapeTableCell(text) {
  return String(text || '').trim().replace(/\|/g, '\\|').replace(/\n/g, ' ');
}

function normalizeFinding(finding) {
  const title = String(finding?.title || '').trim();
  const priority = Number(finding?.priority);
  const confidenceScore = Number(finding?.confidence_score);
  const path = normalizePath(finding?.path);
  const line = Number(finding?.line);
  const rawStartLine = Number(finding?.start_line);
  const startLine = Number.isInteger(rawStartLine) && rawStartLine > 0 ? rawStartLine : null;
  const body = String(finding?.body || '').trim();
  const rawSuggestion = finding?.suggestion != null ? String(finding.suggestion) : '';
  const suggestion = rawSuggestion.length > 0 ? rawSuggestion : null;
  const reasoning = String(finding?.reasoning || '').trim();
  return { title, priority, confidenceScore, path, line, startLine, reasoning, body, suggestion };
}

function resolveModel(parsed, env) {
  const envModel = String(env.CODEX_REVIEW_MODEL || '').trim();
  const selfReported = String(parsed?.model || '').trim();
  const raw = envModel || selfReported || 'unknown';
  // Allowlist: keep only safe characters for Markdown rendering.
  const matches = raw.match(/[A-Za-z0-9._: -]+/g);
  return matches && matches.length > 0 ? matches.join(' ').slice(0, 80) : 'unknown';
}

function isValidFinding(finding) {
  const validRange = finding.startLine === null || finding.startLine <= finding.line;
  return finding.title && finding.path && Number.isInteger(finding.line) && finding.line > 0 && finding.body &&
    Number.isInteger(finding.priority) && finding.priority >= 0 && finding.priority <= 3 &&
    Number.isFinite(finding.confidenceScore) && finding.confidenceScore >= 0 && finding.confidenceScore <= 1 &&
    validRange;
}

module.exports = async function publish({ github, context, core, process }) {
  const rawMaxInline = Number(process.env.MAX_INLINE_CONVERSATIONS);
  const maxInlineConversations = Number.isFinite(rawMaxInline) && rawMaxInline > 0 ? rawMaxInline : 20;
  const rawMaxBody = Number(process.env.GITHUB_MAX_BODY_CHARS);
  const githubMaxBodyChars = Number.isFinite(rawMaxBody) && rawMaxBody > 0 ? rawMaxBody : 65536;
  const rawMinConfidence = Number(process.env.MIN_CONFIDENCE);
  const minConfidence = Number.isFinite(rawMinConfidence)
    ? Math.min(1, Math.max(0, rawMinConfidence))
    : 0;
  const issue_number = context.payload.pull_request.number;
  const { owner, repo } = context.repo;
  const prHeadSha = context.payload.pull_request.head.sha;

  const codexReview = fs.readFileSync('.codex/review-output.json', 'utf8');
  const parsed = parseStructuredReview(codexReview);
  const parsedFindings = Array.isArray(parsed?.findings) ? parsed.findings : [];
  const allFindings = parsedFindings.map(normalizeFinding);
  const summaryText = String(parsed?.summary || '').trim();
  const changes = Array.isArray(parsed?.changes) ? parsed.changes.map(c => String(c).trim()).filter(Boolean) : [];
  const files = Array.isArray(parsed?.files) ? parsed.files : [];
  const overallCorrectness = String(parsed?.overall_correctness || '').trim();
  const overallConfidenceScore = Number(parsed?.overall_confidence_score);
  const model = resolveModel(parsed, process.env);

  // Filter out incomplete findings before sorting so NaN values cannot
  // cause unstable ordering in the comparator.
  const findings = allFindings.filter(isValidFinding);
  let skippedIncomplete = allFindings.length - findings.length;

  // Detect schema-incompatible payload: model returned parseable JSON with findings,
  // but none survived validation. Show raw fallback instead of a misleading clean review.
  const forceRawFallback = parsed !== null && parsedFindings.length > 0 && findings.length === 0;

  // Sort findings: P0 first, then by confidence descending within same priority
  findings.sort((a, b) => {
    if (a.priority !== b.priority) return a.priority - b.priority;
    return b.confidenceScore - a.confidenceScore;
  });

  const diffText = fs.readFileSync('.codex/pr.diff', 'utf8');
  const addedByFile = parseAddedLinesByFile(diffText);
  const totalChangedFiles = (diffText.match(/^diff --git /gm) || []).length;

  const reviewComments = [];
  let skippedInvalidLocation = 0;
  let skippedLowConfidence = 0;
  let skippedTruncated = 0;

  const existingReviewComments = await github.paginate(github.rest.pulls.listReviewComments, {
    owner,
    repo,
    pull_number: issue_number,
    per_page: 100,
  });
  const existingInlineMarkers = new Set(
    existingReviewComments
      .filter((comment) => comment.user?.type === 'Bot')
      .map((comment) => {
        const match = comment.body?.match(/<!-- codex-inline:([a-f0-9]{16}) -->/);
        return match ? match[1] : null;
      })
      .filter(Boolean),
  );

  for (const finding of findings) {
    if (finding.confidenceScore < minConfidence) {
      skippedLowConfidence += 1;
      continue;
    }

    const addedLines = addedByFile.get(finding.path);
    if (!addedLines || !addedLines.has(finding.line)) {
      skippedInvalidLocation += 1;
      continue;
    }

    const signature = crypto
      .createHash('sha256')
      .update(`${finding.path}|${finding.line}|${finding.title}|${finding.priority}`)
      .digest('hex')
      .slice(0, 16);
    if (existingInlineMarkers.has(signature)) {
      continue;
    }

    const alertType = { 0: 'CAUTION', 1: 'WARNING', 2: 'NOTE', 3: 'NOTE' }[finding.priority] || 'NOTE';
    const suggestionBlock = finding.suggestion
      ? `\n\n\`\`\`suggestion\n${finding.suggestion}\n\`\`\``
      : '';
    const reasoningBlock = finding.reasoning && finding.priority > 0
      ? `\n\n<details>\n<summary>Reasoning</summary>\n\n${finding.reasoning}\n\n</details>`
      : '';
    const maxInlineBodyChars = 65000;
    let commentBody = `> [!${alertType}]\n> **${finding.title}**\n\n${finding.body}${reasoningBlock}${suggestionBlock}\n\n<!-- codex-inline:${signature} -->`;
    if (commentBody.length > maxInlineBodyChars) {
      skippedTruncated += 1;
      commentBody = `> [!${alertType}]\n> **${finding.title}**\n\n${finding.body}\n\n...(reasoning/suggestion truncated to fit GitHub limits)\n\n<!-- codex-inline:${signature} -->`;
      if (commentBody.length > maxInlineBodyChars) {
        const truncSuffix = `\n\n...(truncated)\n\n<!-- codex-inline:${signature} -->`;
        commentBody = commentBody.slice(0, Math.max(0, maxInlineBodyChars - truncSuffix.length)) + truncSuffix;
      }
    }
    const commentObj = {
      path: finding.path,
      line: finding.line,
      side: 'RIGHT',
      body: commentBody,
    };
    if (finding.startLine && Number.isInteger(finding.startLine) && finding.startLine > 0 && finding.startLine < finding.line && addedLines.has(finding.startLine)) {
      commentObj.start_line = finding.startLine;
      commentObj.start_side = 'RIGHT';
    }
    reviewComments.push(commentObj);

    if (reviewComments.length >= maxInlineConversations) {
      break;
    }
  }

  const reviewMarker = '<!-- codex-pr-review -->';
  const rawMaxSummary = Number(process.env.MAX_SUMMARY_CHARS);
  const maxSummaryChars = Number.isFinite(rawMaxSummary) && rawMaxSummary > 0 ? rawMaxSummary : 4000;
  const rawMaxChange = Number(process.env.MAX_CHANGE_ITEMS);
  const maxChangeItems = Number.isFinite(rawMaxChange) && rawMaxChange > 0 ? rawMaxChange : 50;
  const rawMaxFiles = Number(process.env.MAX_FILES_IN_TABLE);
  const maxFilesInTable = Number.isFinite(rawMaxFiles) && rawMaxFiles > 0 ? rawMaxFiles : 100;
  const rawMaxReviewBody = Number(process.env.MAX_REVIEW_BODY_CHARS);
  const maxReviewBodyChars = Number.isFinite(rawMaxReviewBody) && rawMaxReviewBody > 0 ? rawMaxReviewBody : 60000;

  function buildVerdictSection() {
    const allowedVerdicts = new Set(['patch is correct', 'patch is incorrect']);
    if (!allowedVerdicts.has(overallCorrectness)) return '';
    const clamped = Number.isFinite(overallConfidenceScore)
      ? Math.max(0, Math.min(1, overallConfidenceScore))
      : null;
    const confidence = clamped !== null ? ` (confidence: ${clamped.toFixed(2)})` : '';
    const verdict = overallCorrectness.charAt(0).toUpperCase() + overallCorrectness.slice(1);
    return `> **Verdict:** ${verdict}${confidence}`;
  }

  // "N out of N" format matches Copilot's review output.
  function buildReviewedLine(commentCount) {
    const commentLabel = commentCount > 0 ? `${commentCount} comment(s)` : 'no new comments';
    return `Codex reviewed ${totalChangedFiles} out of ${totalChangedFiles} changed files in this pull request and generated ${commentLabel}.`;
  }

  function buildFirstReviewBody(commentCount) {
    const reviewedLine = buildReviewedLine(commentCount);
    const sections = ['## Pull request overview'];
    if (summaryText) {
      const summary = summaryText.length > maxSummaryChars
        ? `${summaryText.slice(0, maxSummaryChars)}\n\n...(summary truncated)`
        : summaryText;
      sections.push(summary);
    }
    const verdictSection = buildVerdictSection();
    if (verdictSection) {
      sections.push(verdictSection);
    }
    if (changes.length > 0) {
      const limitedChanges = changes.slice(0, maxChangeItems);
      const changeLines = limitedChanges.map(c => `- ${c}`);
      if (changes.length > maxChangeItems) {
        changeLines.push(`- ...and ${changes.length - maxChangeItems} more change(s)`);
      }
      sections.push(`**Changes:**\n${changeLines.join('\n')}`);
    }
    let fileTable = '';
    if (files.length > 0) {
      const limitedFiles = files.slice(0, maxFilesInTable);
      const rows = limitedFiles.map(f => `| \`${normalizePath(f.path)}\` | ${escapeTableCell(f.description)} |`);
      if (files.length > maxFilesInTable) {
        rows.push(`| ... | ${files.length - maxFilesInTable} more file(s) not shown |`);
      }
      fileTable = `| File | Description |\n| ---- | ----------- |\n${rows.join('\n')}`;
    }
    const reviewedSection = fileTable
      ? `### Reviewed changes\n\n${reviewedLine}\n\n<details>\n<summary>Show a summary per file</summary>\n\n${fileTable}\n\n</details>`
      : `### Reviewed changes\n\n${reviewedLine}`;
    sections.push(reviewedSection);
    let body = sections.join('\n\n');
    if (body.length > maxReviewBodyChars) {
      body = `${body.slice(0, maxReviewBodyChars)}\n\n...(review truncated to fit GitHub limits)`;
    }
    return body;
  }

  function buildSubsequentReviewBody(commentCount) {
    const reviewedLine = buildReviewedLine(commentCount);
    const verdictSection = buildVerdictSection();
    const sections = ['## Pull request overview', reviewedLine];
    if (verdictSection) {
      sections.push(verdictSection);
    }
    return sections.join('\n\n');
  }

  function buildMetadataSection(skippedLoc, skippedInc, skippedConf, skippedTrunc, error) {
    const notes = [
      skippedLoc > 0 ? `Skipped ${skippedLoc} finding(s) not on changed RIGHT-side lines.` : null,
      skippedInc > 0 ? `Skipped ${skippedInc} incomplete finding(s).` : null,
      skippedConf > 0 ? `Skipped ${skippedConf} finding(s) below confidence threshold.` : null,
      skippedTrunc > 0 ? `Truncated ${skippedTrunc} comment(s) to fit GitHub limits.` : null,
      error ? `Failed to post inline conversations: ${error}` : null,
    ].filter(Boolean);
    return notes.length > 0 ? `\n\n<details>\n<summary>Review metadata</summary>\n\n${notes.join('\n')}\n\n</details>` : '';
  }

  function buildFooter() {
    const effort = String(process.env.CODEX_REVIEW_EFFORT || '').trim();
    const effortSuffix = effort ? ` (effort: ${effort})` : '';
    return `\n\n---\n*Generated by [Codex Review](${process.env.RUN_URL}) using ${model}${effortSuffix}*`;
  }

  // GitHub hard limit for review body is 65,536 characters.
  // Apply this after all sections (marker, metadata, footer) are assembled.
  function capReviewBody(body) {
    if (body.length <= githubMaxBodyChars) return body;
    const suffix = '\n\n...(review truncated to fit GitHub limits)';
    return body.slice(0, githubMaxBodyChars - suffix.length) + suffix;
  }

  // Build a Markdown code fence that cannot be broken by backticks in content.
  function buildSafeFence(content) {
    const runs = content.match(/`+/g) || [];
    const maxRun = runs.length > 0 ? Math.max(...runs.map(r => r.length)) : 0;
    return '`'.repeat(Math.max(3, maxRun + 1));
  }

  function buildFallbackBody() {
    const maxFallbackChars = 12000;
    const raw = codexReview.trim();
    const limited = raw.length > maxFallbackChars
      ? `${raw.slice(0, maxFallbackChars)}\n...(truncated)`
      : raw;
    if (!raw) return '## Pull request overview\n\nCodex returned an empty response.';
    const fence = buildSafeFence(limited);
    return `## Pull request overview\n\nCould not parse structured Codex output. Raw response:\n\n${fence}\n${limited}\n${fence}`;
  }

  // Detect isFirstReview via pulls.listReviews
  const existingReviews = await github.paginate(github.rest.pulls.listReviews, {
    owner,
    repo,
    pull_number: issue_number,
    per_page: 100,
  });
  const isFirstReview = !existingReviews.some(
    (review) => review.user?.type === 'Bot' && review.body?.includes(reviewMarker),
  );

  // Each push creates a NEW review (never upserted). This matches
  // Copilot's behavior: every synchronize event produces a fresh review
  // so the PR timeline shows the review history per push.
  let inlineError = '';
  try {
    const commentCount = reviewComments.length;
    let body;
    if (!parsed || forceRawFallback) {
      body = buildFallbackBody();
    } else if (isFirstReview) {
      body = buildFirstReviewBody(commentCount);
    } else {
      body = buildSubsequentReviewBody(commentCount);
    }
    body += buildMetadataSection(skippedInvalidLocation, skippedIncomplete, skippedLowConfidence, skippedTruncated, '');
    body += buildFooter();
    body = capReviewBody(`${reviewMarker}\n\n${body}`);

    const reviewPayload = {
      owner,
      repo,
      pull_number: issue_number,
      commit_id: prHeadSha,
      event: 'COMMENT',
      body,
    };
    if (reviewComments.length > 0) {
      reviewPayload.comments = reviewComments;
    }
    await github.rest.pulls.createReview(reviewPayload);
  } catch (error) {
    inlineError = error.message;
    core.warning(`Failed to create review: ${inlineError}`);

    // If review with comments failed, retry without comments
    if (reviewComments.length > 0) {
      try {
        let body;
        if (!parsed || forceRawFallback) {
          body = buildFallbackBody();
        } else if (isFirstReview) {
          body = buildFirstReviewBody(0);
        } else {
          body = buildSubsequentReviewBody(0);
        }
        body += buildMetadataSection(skippedInvalidLocation, skippedIncomplete, skippedLowConfidence, skippedTruncated, inlineError);
        body += buildFooter();
        body = capReviewBody(`${reviewMarker}\n\n${body}`);

        await github.rest.pulls.createReview({
          owner,
          repo,
          pull_number: issue_number,
          commit_id: prHeadSha,
          event: 'COMMENT',
          body,
        });
      } catch (retryError) {
        core.warning(`Failed to create fallback review: ${retryError.message}`);
      }
    }
  }
};
