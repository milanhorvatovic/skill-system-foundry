# YAML 1.2.2 conformance corpus

This directory holds a curated set of YAML fixtures used by
`tests/test_yaml_conformance.py` to verify that the in-repo
`parse_yaml_subset` parser behaves predictably across the supported
grammar surface, the documented divergences, and the spec-pinned
rejections.

All current fixtures are `"origin": "original"` — authored in this
repository to exercise specific parser branches.  When the first
upstream-vendored fixtures land (sourced from the YAML Test Suite at
https://github.com/yaml/yaml-test-suite under MIT), re-add a
top-level `LICENSE` (upstream MIT verbatim) and a
`THIRD-PARTY-NOTICES.md` entry at the repo root pinning the commit
SHA and date.

## Layout

```
tests/fixtures/yaml-conformance/
├── README.md                  # this file
├── digests.txt                # sha256sum format, one .yaml per line
├── supported/                 # parses identically to .expected.json's parsed dict
├── divergent/                 # parses with a specific finding(s) and parsed dict
└── rejected/                  # raises ValueError matching error_substring
```

Top-level directories under this corpus root are restricted to
`supported/`, `divergent/`, `rejected/` (G100).  Nested subdirectories
inside each bucket are allowed for organisation when a bucket grows
beyond ~15 fixtures (G101).

## Curation rules

1. **Substring targeting (G20).**  The `findings[].substring` and
   `error_substring` fields in `.expected.json` are matched as literal
   substrings against parser output.  Choose the shortest fragment
   that uniquely identifies the spec case being tested.  For the three
   pinned rejections (G46), target the `<construct-id>` token; for all
   other findings target the **stable spec-description portion**, not
   the advice tail after the last `;` (e.g. `"unquoted value starts
   with '*'"`, not `"wrap value in single quotes"`).

2. **Mapping-form curation (G59).**  Every `divergent/` fixture that
   targets a plain-scalar branch uses mapping form
   (`key: <divergent-value>`).  This matches the parser's actual
   detection path — divergence checks fire during key descent.

3. **No whitespace in paths (G132).**  Fixture filenames use hyphens
   and dots only.  `digests.txt` parses on the first run of
   whitespace, so paths with embedded spaces or tabs would split
   incorrectly.  The refresh script enforces this rule.

4. **Sidecars are per-base (G135).**  A logical case `foo` ships with
   `foo.expected.json` and `foo.meta.json` once, regardless of how
   many `.lf.yaml` / `.crlf.yaml` / `.mixed.yaml` variants exist.  See
   §5.3 of the design plan.

5. **Per-bucket variant rules (G56).**  `supported/` and `divergent/`
   require the full `.lf.yaml` + `.crlf.yaml` + `.mixed.yaml` triplet
   per logical case.  `rejected/` requires only `.lf.yaml` (rejection
   depends on grammar, not encoding).

6. **Manifest scope (G99 / G105).**  `digests.txt` covers only the
   `.yaml` fixture bytes — it does not include its own digest, and
   `.expected.json` / `.meta.json` sidecars are excluded (they are
   metadata, not fixture bytes; stdlib `json` is indifferent to line
   endings).

## Refreshing `digests.txt`

Any PR that adds, edits, or removes a fixture variant must regenerate
the manifest.  The harness's per-variant SHA-256 check catches stale
digests automatically (G51), but the contributor is expected to keep
the manifest current locally:

```
python .github/scripts/refresh-yaml-corpus-digests.py
python .github/scripts/refresh-yaml-corpus-digests.py --check
```
