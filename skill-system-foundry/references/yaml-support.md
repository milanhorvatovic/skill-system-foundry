# YAML support — supported grammar, divergences, and conformance scope

This reference documents the YAML surface that the in-repo `parse_yaml_subset` parser accepts, the divergences it actively flags, and the limits authors should plan around.

## Supported grammar surface

- Mapping (`key: value`) at any nesting depth.
- Nested mappings via indentation.
- Block sequences (`- item`) of plain scalars and of mappings.
- Block scalars: literal `|`, folded `>`, with optional chomping (`|-`, `|+`, `>-`, `>+`).
- Plain, single-quoted, and double-quoted scalars.
- Comments (`# ...`) — full-line and trailing inline.

All scalar values are returned as strings — no type coercion for numbers, booleans, or null.

## Divergence detection

Plain-scalar values that strict YAML 1.2 parsers would interpret differently are flagged with structured findings rather than silently mis-parsed. The detection covers leading flow / alias / reserved / directive / block-entry / mapping-key / anchor / tag / quote indicators, plus colon-space inside an unquoted value. Findings carry `[spec]` tags and quoting advice; consumers act on them.

## Pinned grammar-gap rejections

Three constructs raise `ValueError` at parse time, with the message shape:

```
unsupported YAML 1.2.2 construct: <construct-id> (spec §<n.n>)
```

Construct IDs (mirrored in `scripts/lib/configuration.yaml#yaml_conformance.construct_ids`):

- `anchor-with-trailing-in-key` — `&name key:` (spec §6.9).
- `indent-indicator-block-scalar` — `key: |2`, `key: >-3`, etc. (spec §8.1.1).
- `tag-in-mapping-key` — `!!str key:`, `!tag key:` (spec §6.9).

Plain-scalar usage of anchor / tag indicators in **value** position remains a `WARN`-level finding — only the mapping-key position is upgraded.

## Line-ending contract

`parse_yaml_subset` accepts LF, CRLF, CR, and mixed line terminators. Every string value returned uses LF-only line terminators regardless of input style (defense in depth — `load_frontmatter` and the prose extractor normalise at every text-ingestion boundary).

## Conformance scope

These guarantees describe **the meta-skill's own YAML surface**. Third-party tools that consume skill bundles use their own YAML parsers; their behaviour is not part of this contract. The `tests/fixtures/yaml-conformance/` corpus exercises this surface end to end via `tests/test_yaml_conformance.py` and the `--json` slot emitted by `scripts/yaml_conformance_report.py`.

## Out of scope

The parser does **not** support:

- Anchors and aliases as referenced nodes (`&` / `*`).
- Flow syntax (`{a: 1}`, `[1, 2]`).
- Multi-document streams (`---` separators between documents).
- Tags as type / kind selectors in structural positions.
- Indentation-indicator block scalar headers.
- Type coercion (every value is a string).
- Top-level scalars or sequences. `parse_yaml_subset` returns `{}` when the root is not a mapping; prose snippets that need to exercise divergence detection should use mapping form (`key: <divergent-value>`) so the divergence check fires during key descent.
