"""Load-time structure validation for ``configuration.yaml``.

``constants.py`` dereferences a fixed set of key paths out of the parsed
configuration mapping (and converts numeric scalars with ``int()`` /
``float()``).  A missing or wrong-typed key in ``configuration.yaml``
would otherwise surface as a bare ``KeyError`` / ``TypeError`` /
``ValueError`` at *import* time, with a traceback that names a private
local (``_skill``, ``_eval``) rather than the offending YAML key — an
opaque failure for anyone editing the config or running a stale
checkout.

This module guards exactly the key paths ``constants.py`` consumes.  It
checks presence and basic shape (mapping vs list vs scalar) and that
scalars destined for ``int()`` / ``float()`` actually convert.  On the
first problem it raises :class:`ConfigurationError` with a message that
names the offending dotted key path, e.g.::

    ConfigurationError: missing required key
    'skill.description.evaluation.default_min_precision' in configuration.yaml

The scope is deliberately narrow: this is not a general JSON-schema
engine.  It validates the structural shape ``constants.py`` relies on so
the loader fails fast and clearly.  Deeper per-entry semantics (empty /
duplicate / path-traversal list entries, range bounds on integers) stay
in ``constants.py`` where the normalized values are produced — this
module only guarantees the dereferences in that module will not raise an
unhelpful builtin error.

The function takes a plain ``dict`` so it can be unit-tested in
isolation without reading the on-disk file.  The stdlib-only YAML subset
parser returns every scalar as a ``str``, so the numeric checks below
attempt the same conversion ``constants.py`` performs.
"""

CONFIG_FILE_NAME = "configuration.yaml"


class ConfigurationError(RuntimeError):
    """Raised when ``configuration.yaml`` is missing a required key or
    a key has the wrong shape for what ``constants.py`` expects.

    Subclasses ``RuntimeError`` so the inline fail-fast checks in
    ``constants.py`` (which raise ``RuntimeError`` for per-entry semantic
    problems) and this structural loader present one exception family to
    callers — ``except RuntimeError`` catches both, and existing tests
    asserting ``RuntimeError`` on a malformed config continue to hold.
    """


def _format_path(path: tuple[str, ...]) -> str:
    """Render a key-path tuple as a dotted string for diagnostics."""
    return ".".join(path)


def _require_key(parent: dict, path: tuple[str, ...]) -> object:
    """Return ``parent[path[-1]]`` or raise naming the dotted *path*.

    *parent* is the already-resolved mapping that should contain the
    final segment of *path*; the full *path* is used only for the
    diagnostic message.
    """
    key = path[-1]
    if key not in parent:
        raise ConfigurationError(
            f"missing required key '{_format_path(path)}' in {CONFIG_FILE_NAME}"
        )
    return parent[key]


def _require_mapping(parent: dict, path: tuple[str, ...]) -> dict:
    """Return ``parent[path[-1]]`` ensuring it is a mapping.

    A key authored with no children (``stats:`` followed by no indented
    lines) parses as the empty string ``""`` rather than an empty dict
    in the stdlib YAML subset, so a blank value here is rejected with
    the same diagnostic as a scalar.  Leaf mappings such as
    ``skill.allowed_tools.fence_languages`` and ``stats.line_endings``
    have no required children that would catch the blank form
    downstream — ``constants.py`` would then crash on ``.items()`` /
    ``.get()`` against ``""``.  Failing here keeps the diagnostic
    actionable and the validator a faithful guard for the dereferences
    that follow.
    """
    value = _require_key(parent, path)
    if not isinstance(value, dict):
        raise ConfigurationError(
            f"key '{_format_path(path)}' in {CONFIG_FILE_NAME}: expected a "
            f"mapping, got {type(value).__name__}"
        )
    return value


def _require_list(parent: dict, path: tuple[str, ...]) -> list:
    """Return ``parent[path[-1]]`` ensuring it is a list."""
    value = _require_key(parent, path)
    if not isinstance(value, list):
        raise ConfigurationError(
            f"key '{_format_path(path)}' in {CONFIG_FILE_NAME}: expected a "
            f"list, got {type(value).__name__}"
        )
    return value


def _require_scalar(parent: dict, path: tuple[str, ...]) -> str:
    """Return ``parent[path[-1]]`` ensuring it is a scalar (not a
    mapping or list).

    The YAML subset parser returns scalars as ``str``; a key with no
    value is returned as ``""``.  A mapping or list here means the key
    was authored as a nested structure where ``constants.py`` expects a
    plain value.
    """
    value = _require_key(parent, path)
    if isinstance(value, (dict, list)):
        raise ConfigurationError(
            f"key '{_format_path(path)}' in {CONFIG_FILE_NAME}: expected a "
            f"scalar string value, got {type(value).__name__}"
        )
    return str(value)


def _require_int(parent: dict, path: tuple[str, ...]) -> None:
    """Ensure ``parent[path[-1]]`` is a scalar that ``int()`` accepts.

    Mirrors the ``int(...)`` conversion ``constants.py`` performs so a
    malformed numeric (``max_length: abc``) produces a message naming
    the key instead of a bare ``ValueError`` at import.
    """
    value = _require_scalar(parent, path)
    try:
        int(value)
    except (TypeError, ValueError):
        raise ConfigurationError(
            f"key '{_format_path(path)}' in {CONFIG_FILE_NAME}: expected an "
            f"integer, got {value!r}"
        ) from None


def _require_float(parent: dict, path: tuple[str, ...]) -> None:
    """Ensure ``parent[path[-1]]`` is a scalar that ``float()`` accepts."""
    value = _require_scalar(parent, path)
    try:
        float(value)
    except (TypeError, ValueError):
        raise ConfigurationError(
            f"key '{_format_path(path)}' in {CONFIG_FILE_NAME}: expected a "
            f"number, got {value!r}"
        ) from None


def validate_config_structure(config: dict) -> None:
    """Validate the structure ``constants.py`` depends on.

    Walks every key path ``constants.py`` dereferences from the parsed
    configuration, checking presence and basic shape (mapping / list /
    scalar) and that scalars converted with ``int()`` / ``float()``
    convert cleanly.  Raises :class:`ConfigurationError` naming the
    offending dotted key path on the first problem; returns ``None`` when
    every consumed path is present and well-shaped.

    Does not mutate *config*.  Per-entry semantic checks (empty /
    duplicate / traversal entries, integer range bounds) remain in
    ``constants.py``; this guards the dereferences themselves.
    """
    if not isinstance(config, dict):
        raise ConfigurationError(
            f"{CONFIG_FILE_NAME} did not parse to a mapping, got "
            f"{type(config).__name__}"
        )

    _validate_skill(config)
    _validate_plain_scalar(config)
    _validate_path_resolution(config)
    _validate_prose_yaml(config)
    _validate_yaml_conformance(config)
    _validate_codex_config(config)
    _validate_dependency_direction(config)
    _validate_role_composition(config)
    _validate_orphan_references(config)
    _validate_bundle(config)
    _validate_stats(config)


def _validate_skill(config: dict) -> None:
    """Guard the ``skill`` section and everything ``constants.py`` reads
    beneath it."""
    skill = _require_mapping(config, ("skill",))

    # skill.name
    name = _require_mapping(skill, ("skill", "name"))
    _require_int(name, ("skill", "name", "max_length"))
    _require_int(name, ("skill", "name", "min_length"))
    _require_scalar(name, ("skill", "name", "format_pattern"))
    _require_list(name, ("skill", "name", "reserved_words"))
    _require_list(name, ("skill", "name", "windows_reserved_names"))

    # skill.description
    desc = _require_mapping(skill, ("skill", "description"))
    _require_int(desc, ("skill", "description", "max_length"))
    _require_scalar(desc, ("skill", "description", "xml_tag_pattern"))
    _require_list(desc, ("skill", "description", "trigger_phrases"))

    voice = _require_mapping(desc, ("skill", "description", "voice_patterns"))
    voice_base = ("skill", "description", "voice_patterns")
    _require_scalar(voice, voice_base + ("first_person",))
    _require_scalar(voice, voice_base + ("first_person_plural",))
    _require_scalar(voice, voice_base + ("second_person",))
    _require_scalar(voice, voice_base + ("imperative_start",))

    _validate_evaluation(desc)
    _validate_structural_rules(desc)

    # skill.body
    body = _require_mapping(skill, ("skill", "body"))
    _require_int(body, ("skill", "body", "max_lines"))
    refs = _require_mapping(body, ("skill", "body", "reference_patterns"))
    _require_scalar(refs, ("skill", "body", "reference_patterns", "markdown_link"))
    _require_scalar(refs, ("skill", "body", "reference_patterns", "backtick"))

    # skill.compatibility
    compat = _require_mapping(skill, ("skill", "compatibility"))
    _require_int(compat, ("skill", "compatibility", "max_length"))

    # skill.known_frontmatter_keys
    _require_list(skill, ("skill", "known_frontmatter_keys"))

    # skill.frontmatter_suggestions
    fm = _require_mapping(skill, ("skill", "frontmatter_suggestions"))
    _require_int(fm, ("skill", "frontmatter_suggestions", "max_matches"))
    _require_float(fm, ("skill", "frontmatter_suggestions", "cutoff"))

    _validate_allowed_tools(skill)

    # skill.metadata
    metadata = _require_mapping(skill, ("skill", "metadata"))
    version = _require_mapping(metadata, ("skill", "metadata", "version"))
    _require_scalar(version, ("skill", "metadata", "version", "pattern"))
    author = _require_mapping(metadata, ("skill", "metadata", "author"))
    _require_int(author, ("skill", "metadata", "author", "max_length"))

    # skill.license
    license_section = _require_mapping(skill, ("skill", "license"))
    _require_list(license_section, ("skill", "license", "known_spdx"))

    # skill.recognized_subdirectories
    _require_list(skill, ("skill", "recognized_subdirectories"))

    # skill.capability_frontmatter
    cap_fm = _require_mapping(skill, ("skill", "capability_frontmatter"))
    _require_list(
        cap_fm, ("skill", "capability_frontmatter", "skill_only_fields")
    )


def _validate_evaluation(desc: dict) -> None:
    """Guard ``skill.description.evaluation`` and its coverage subtree."""
    base = ("skill", "description", "evaluation")
    evaluation = _require_mapping(desc, base)
    _require_float(evaluation, base + ("default_min_precision",))
    _require_float(evaluation, base + ("default_min_recall",))
    _require_float(evaluation, base + ("heuristic_min_overlap",))
    _require_int(evaluation, base + ("max_prompt_chars",))
    _require_float(evaluation, base + ("diversity_distinct_bigram_min_ratio",))
    _require_int(evaluation, base + ("min_prompts_per_side",))
    _require_int(evaluation, base + ("recommended_prompts_per_side",))
    _require_list(evaluation, base + ("stopwords",))

    cov_base = base + ("coverage",)
    coverage = _require_mapping(evaluation, cov_base)
    _require_scalar(coverage, cov_base + ("corpus_root_relative",))
    # allowed_missing_corpus and freshness_check_enabled are optional in
    # constants.py (.get with a default); their shape is validated there
    # when present, so they are not required here.


def _validate_structural_rules(desc: dict) -> None:
    """Guard ``skill.description.structural_rules``."""
    base = ("skill", "description", "structural_rules")
    structural = _require_mapping(desc, base)
    _require_int(structural, base + ("trigger_minimum_count",))
    _require_list(structural, base + ("negative_trigger_phrases",))
    _require_list(structural, base + ("filler_phrases",))
    _require_int(structural, base + ("filler_lookahead_tokens",))
    _require_list(structural, base + ("boundary_clause_phrases",))
    _require_int(structural, base + ("length_tier_warn_below",))
    _require_int(structural, base + ("length_tier_warn_above",))
    _require_int(structural, base + ("vocabulary_minimum",))
    _require_list(structural, base + ("vocabulary_list",))
    _require_int(structural, base + ("redundancy_min_count",))
    _require_float(structural, base + ("redundancy_max_ratio",))
    _require_list(structural, base + ("stopwords",))


def _validate_allowed_tools(skill: dict) -> None:
    """Guard ``skill.allowed_tools`` and the claude_code catalog."""
    base = ("skill", "allowed_tools")
    allowed = _require_mapping(skill, base)
    _require_int(allowed, base + ("max_tools",))
    _require_scalar(allowed, base + ("mcp_tool_pattern",))
    _require_scalar(allowed, base + ("harness_tool_shape_pattern",))

    cat_base = base + ("catalogs",)
    catalogs = _require_mapping(allowed, cat_base)
    cc_base = cat_base + ("claude_code",)
    claude_code = _require_mapping(catalogs, cc_base)
    _require_list(claude_code, cc_base + ("harness_tools",))
    _require_list(claude_code, cc_base + ("cli_tools",))

    # fence_languages: a mapping of tool-name -> { languages: [...] }.
    fence_base = base + ("fence_languages",)
    fence = _require_mapping(allowed, fence_base)
    for tool_name, entry in fence.items():
        entry_path = fence_base + (str(tool_name),)
        if not isinstance(entry, dict):
            raise ConfigurationError(
                f"key '{_format_path(entry_path)}' in {CONFIG_FILE_NAME}: "
                f"expected a mapping, got {type(entry).__name__}"
            )
        _require_list(entry, entry_path + ("languages",))


def _validate_plain_scalar(config: dict) -> None:
    """Guard ``plain_scalar`` indicators and context whitespace."""
    plain = _require_mapping(config, ("plain_scalar",))
    indicators = _require_mapping(plain, ("plain_scalar", "indicators"))
    ind_base = ("plain_scalar", "indicators")
    for key in (
        "flow", "alias", "reserved", "directive", "block_entry",
        "mapping_key", "anchor", "block_scalar", "quote_single",
        "quote_double", "tag",
    ):
        _require_scalar(indicators, ind_base + (key,))
    _require_list(plain, ("plain_scalar", "context_whitespace"))


def _validate_path_resolution(config: dict) -> None:
    """Guard ``path_resolution`` and its degraded_symlink subtree."""
    base = ("path_resolution",)
    pr = _require_mapping(config, base)
    _require_scalar(pr, base + ("rule_name",))
    _require_scalar(pr, base + ("documentation_path",))
    _require_list(pr, base + ("reference_extensions",))

    ds_base = base + ("degraded_symlink",)
    ds = _require_mapping(pr, ds_base)
    _require_int(ds, ds_base + ("max_bytes",))
    _require_list(ds, ds_base + ("foundry_extensions",))


def _validate_prose_yaml(config: dict) -> None:
    """Guard ``prose_yaml``."""
    base = ("prose_yaml",)
    prose = _require_mapping(config, base)
    _require_scalar(prose, base + ("opt_out_marker",))
    _require_list(prose, base + ("in_scope_globs",))


def _validate_yaml_conformance(config: dict) -> None:
    """Guard ``yaml_conformance``."""
    base = ("yaml_conformance",)
    yc = _require_mapping(config, base)
    _require_list(yc, base + ("construct_ids",))


def _validate_codex_config(config: dict) -> None:
    """Guard ``codex_config`` interface / dependencies / schema key sets."""
    base = ("codex_config",)
    codex = _require_mapping(config, base)

    iface_base = base + ("interface",)
    iface = _require_mapping(codex, iface_base)
    _require_int(iface, iface_base + ("max_display_name_length",))
    _require_int(iface, iface_base + ("max_short_description_length",))
    _require_scalar(iface, iface_base + ("hex_color_pattern",))

    deps_base = base + ("dependencies",)
    deps = _require_mapping(codex, deps_base)
    _require_list(deps, deps_base + ("known_tool_types",))
    _require_list(deps, deps_base + ("known_transports",))

    _require_list(codex, base + ("known_top_level_keys",))
    _require_list(codex, base + ("known_interface_keys",))
    _require_list(codex, base + ("known_policy_keys",))
    _require_list(codex, base + ("known_dependencies_keys",))
    _require_list(codex, base + ("known_tool_keys",))


def _validate_dependency_direction(config: dict) -> None:
    """Guard ``dependency_direction`` patterns."""
    base = ("dependency_direction",)
    dep = _require_mapping(config, base)
    _require_scalar(dep, base + ("roles_ref_pattern",))
    _require_scalar(dep, base + ("sibling_capability_ref_pattern",))


def _validate_role_composition(config: dict) -> None:
    """Guard ``role_composition``."""
    base = ("role_composition",)
    role = _require_mapping(config, base)
    _require_int(role, base + ("min_skills",))
    _require_scalar(role, base + ("skill_ref_pattern",))
    _require_scalar(role, base + ("capability_ref_pattern",))


def _validate_orphan_references(config: dict) -> None:
    """Guard ``orphan_references.allowed_orphans``.

    The key must be present, but its value may be blank (``""`` / a list)
    — ``constants.py`` coerces the empty form to an empty list.  Only a
    mapping is rejected here as a structural error.
    """
    base = ("orphan_references",)
    orphan = _require_mapping(config, base)
    value = _require_key(orphan, base + ("allowed_orphans",))
    if isinstance(value, dict):
        raise ConfigurationError(
            f"key '{_format_path(base + ('allowed_orphans',))}' in "
            f"{CONFIG_FILE_NAME}: expected a list (or blank), got "
            f"{type(value).__name__}"
        )


def _validate_bundle(config: dict) -> None:
    """Guard ``bundle`` and its long_path subtree."""
    base = ("bundle",)
    bundle = _require_mapping(config, base)
    _require_int(bundle, base + ("max_reference_depth",))
    _require_int(bundle, base + ("description_max_length",))
    _require_int(bundle, base + ("infer_max_walk_depth",))
    _require_list(bundle, base + ("exclude_patterns",))
    _require_list(bundle, base + ("valid_targets",))
    _require_scalar(bundle, base + ("default_target",))

    lp_base = base + ("long_path",)
    long_path = _require_mapping(bundle, lp_base)
    _require_int(long_path, lp_base + ("threshold",))
    _require_int(long_path, lp_base + ("user_prefix_budget",))


def _validate_stats(config: dict) -> None:
    """Guard ``stats.line_endings``."""
    base = ("stats",)
    stats = _require_mapping(config, base)
    _require_mapping(stats, base + ("line_endings",))
    # ``enabled`` is optional (constants.py uses .get with a default and
    # validates the value when present), so it is not required here.
