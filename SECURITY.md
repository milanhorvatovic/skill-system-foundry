# Security

## Reporting a vulnerability

If you believe you have found a security issue in this repository, please open a private report via GitHub Security Advisories (the repository's _Security → Report a vulnerability_ tab) rather than a public issue. Include the affected file, a reproduction, and the impact you observed.

## Threat model for the CLI tools

This repository ships a meta-skill plus a set of standard-library Python tools that operators run locally or in CI: `validate_skill.py`, `audit_skill_system.py`, `bundle.py`, `scaffold.py`, `stats.py`, `evaluate_descriptions.py`, `reference_conformance_report.py`, `yaml_conformance_report.py`, and the CI helpers under `.github/scripts/`. Each takes one or more filesystem paths from its caller and reads (or writes) files under them.

Snyk Code reports many of these path flows as path traversal (`python/PT`). They divide into two classes that the taint tracker does not distinguish; recording the distinction here so the remediation is informed rather than uniform.

### Class A — operator-supplied CLI path (accepted false positive)

The positional/optional path an operator passes to a local CLI tool (the skill directory handed to `validate_skill.py`, the `--root` given to `scaffold.py`, the corpus tree hashed by `refresh-yaml-corpus-digests.py`, …) flows into `open()` or `os.walk`.

A path-traversal finding is a real vulnerability only when the path-supplier has **less privilege than the process** — a web request reaching a server, a setuid binary, a sandboxed job. For these tools the supplier _is_ the operator running the CLI under their own account. They can already read and write any file they point the tool at; pointing it at an absolute path, a sibling directory, or a `/tmp` extraction is the tool's **intended job**. There is no privilege boundary to cross and no trust boundary to enforce.

These findings are therefore accepted as false positives and excluded from Snyk Code in [`.snyk`](.snyk), each with a per-file rationale.

**Why an exclude and not a code fix.** Issue #151 ran a spike to test whether an in-code guard could clear these. Three sanitizer forms — an extracted `realpath`/`commonpath` containment guard, an inline `realpath` + `.startswith(base + os.sep)` check, and `os.path.basename()` — each cleared **0 of 17** findings on `validate_skill.py`. The cause is structural: the containment _base_ is itself the operator-supplied root (`x` validated against `x` proves nothing), so there is no trusted reference for Snyk to recognize a sanitizer against. Snyk Code also does not honor per-finding `.snyk` ignores or inline ignore comments through the CLI, so a whole-file `exclude` (committed and reviewable, with a written reason) is the only available mechanism.

`.github/scripts/tool-catalog-drift.py` mixes Class A path traversal (the `--catalog-path` read/write) with a real network sink (the SSRF, see Class B). Its SSRF is hardened in code and test-guarded, but Snyk Code does not credit the host-allowlist check as a sanitizer — the same custom-sanitizer blindness that defeats the path guards — so neither the SSRF nor the 3 Class A `python/PT` findings can be cleared in code. Keeping the file under SAST would only park false positives Snyk can never resolve, so it is excluded in `.snyk`; the SSRF regression guard is the test suite (`.github/tests/test_tool_catalog_drift.py`), not Snyk.

### Class B — genuine trust boundary (fixed in code)

Where a path or URL crosses a real trust boundary, it is hardened in code (and kept under SAST where Snyk credits the fix):

- **Reference-graph reads** (`lib/references.py`) follow markdown links embedded in _skill content_, which is untrusted when the skill is contributed or integrator-authored. These are contained with `realpath`/`commonpath` against the system root and reject absolute paths, leading `..` segments, and external URL schemes (`resolve_reference_with_reason` / `is_within_directory`). This content-derived flow is not among the Snyk CLI-argument findings.

- **SSRF** in `.github/scripts/tool-catalog-drift.py` `fetch()`: the upstream URL ultimately derives from an operator-pointable config file. `fetch()` validates the scheme (`https`) and host against a **hardcoded** allowlist (`ALLOWED_FETCH_HOSTS`, independent of the config) before the request, and re-validates the landing URL after redirects so a 30x cannot smuggle in an off-allowlist host.

- **Zip-slip** in `tests/test_integration_pipeline.py`: archive extraction goes through `tests/helpers.py:safe_extractall`, which validates each member's resolved destination stays within the (trusted, test-controlled) target before extracting it. `zipfile.extractall` has no `filter=` parameter — that is a `tarfile` feature — so containment is enforced per member explicitly.
