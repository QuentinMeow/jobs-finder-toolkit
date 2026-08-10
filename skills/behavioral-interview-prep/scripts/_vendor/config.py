"""Load the job-hunt configuration (candidate identity, paths, policies).

The toolkit keeps all candidate-specific values OUT of the code and in a
git-ignored ``config.yaml`` at the repo root. This module discovers, loads, and
caches that config and exposes typed accessors so the rest of the toolkit never
hardcodes a name, contact line, filename stem, or profile path.

Discovery order (first match wins):
    1. ``$JOBHUNT_CONFIG``   — explicit path from the environment (if it exists)
    2. nearest ``config.yaml`` walking UP from ``Path.cwd()``, then UP from this
       file's directory, stopping at the first directory that contains a ``.git``
       entry (that repository-boundary directory is itself searched). The boundary
       keeps a git worktree from resolving its parent checkout's config.
    3. ``<repo_root>/config.example.yaml`` — the tracked, neutral placeholder —
       but ONLY when falling back cannot silently point the toolkit at the
       fictional persona while real data is on disk. The fallback:
         * is silent when ``$JOBHUNT_CONFIG`` named an existing file (step 1);
         * prints a ONE-LINE stderr notice (once per process) when no private
           overlay is mounted at the repository boundary — a fresh public clone
           must keep running out of the box against the example data;
         * raises ``ConfigNotFound`` when a ``private/`` overlay IS mounted (real
           data is present, so the fictional persona is the wrong answer), or when
           ``$JOBHUNT_REQUIRE_REAL_CONFIG`` is set to a truthy value.

``<repo_root>`` above is itself DISCOVERED, by the same upward ``.git`` walk — see
``_repo_root``. This module is vendored byte-identically into skills that sit at a
different depth, so counting parents would resolve inside the skill folder there.

A malformed config (a YAML syntax error, or a top level that is not a mapping)
raises ``ConfigError`` instead of degrading to every hardcoded default. A missing
or unreadable file still yields an empty config, exactly as before.

Paths in the config are interpreted RELATIVE TO THE CONFIG FILE'S directory and
resolved to absolute ``Path`` objects.

Config schema::

    candidate:
      name: "Full Name"
      contact_line: "City, ST • email • linkedin"
      name_slug: "First_Last"          # filename-safe person part
      title_slug: "Software_Engineer"  # filename-safe role part
    paths:
      profile_md: "private/me/career/profile.md"
      baseline_yaml: "private/me/career/resume/baseline.yaml"
      reference_docx: "private/me/career/resume/reference.docx"
      company_levels_yaml: "relative/path.yaml"
      applications_root: "private/me/applications"
      discoveries_dir: "private/market/scans/current"
      # Every key below is OPTIONAL; each derives from the two roots above when
      # omitted (see the accessor's docstring for the exact derivation).
      overlay_root: "private"                            # OPTIONAL
      candidate_dir: "applications/0_profile"            # OPTIONAL
      calendar_md: "applications/0_profile/calendar.md"  # OPTIONAL
      blacklist_yaml: "private/market/blacklist.yaml"              # OPTIONAL
      story_bank_dir: "private/me/interviews/story-bank"           # OPTIONAL
      search_profiles_dir: "private/market/searches"               # OPTIONAL
      skill_references_root: "private/skills/skill-notes"          # OPTIONAL
      companies_root: "private/me/interviews/companies"            # OPTIONAL
    job_search:
      default_profile: "default"
    generation:
      mode: token_saving              # token_saving (default) | full
    leak_guard:
      english_word_tokens: ["Green"]  # OPTIONAL; see the accessor's docstring
    outlook_email:
      account: "<personal-mailbox>"  # expected signed-in mailbox; private config only
      client_id: "..."               # public-client app registration ID; not a secret
      tenant: "consumers"             # personal Microsoft accounts only
      company_domains:                # OPTIONAL safe company-domain link mapping
        Example Company: [example.com]
      company_domains_path: "private/email-company-domains.yaml"  # OPTIONAL mapping file
    location_policy:
      metro: [City, ...]          # preferred-metro tokens (candidate-specific)
      remote_tokens: [...]        # OPTIONAL; if omitted use location.py defaults
      us_remote_regions: [...]    # OPTIONAL; if omitted use location.py defaults
      allow_us_remote: true
      us_only: true

The filename stems are composed from ``name_slug`` / ``title_slug`` via
``layout.compose_stem`` so they carry an optional target-position label suffix.
"""

import os
import sys
from functools import lru_cache
from pathlib import Path

import yaml

# config.py lives in automation/shared/, alongside layout.py. Make sure this folder
# is importable so ``import layout`` resolves even when config is imported from a
# context that didn't inject the shared/ bucket onto sys.path.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import layout  # noqa: E402  (import after sys.path bootstrap, by design)

CONFIG_FILENAME = "config.yaml"
EXAMPLE_CONFIG_FILENAME = "config.example.yaml"
ENV_VAR = "JOBHUNT_CONFIG"

# Set to a truthy value to refuse the example fallback everywhere (CI in a
# maintainer checkout, cron jobs, anything that must never run on the persona).
REQUIRE_REAL_CONFIG_ENV_VAR = "JOBHUNT_REQUIRE_REAL_CONFIG"

# The git-ignored private overlay directory, mounted at the repository boundary.
# Its presence means real candidate data is on disk (see the module docstring).
OVERLAY_DIRNAME = "private"

# Marks a repository boundary. A git WORKTREE's ``.git`` is a FILE, not a
# directory, so the walk tests for existence rather than ``is_dir()``.
_GIT_MARKER = ".git"

_FALSEY = {"", "0", "false", "no", "off"}


def _git_boundary(start: Path) -> Path | None:
    """First directory at or above ``start`` holding a ``.git`` entry, else ``None``.

    The single upward ``.git`` walk in this module: both the config search
    (``_search_up``) and the repo-root constant below stop at the SAME directory,
    so a config found by discovery and the root used for the overlay check can
    never come from different trees.
    """
    for parent in (start, *start.parents):
        if (parent / _GIT_MARKER).exists():
            return parent
    return None


def _repo_root(start: Path) -> Path:
    """The project root ``start`` belongs to, found by walking UP (never by counting).

    This file has TWO homes: the canonical ``automation/shared/config.py``, two
    levels below the repo root, and a byte-identical vendored copy at
    ``skills/<skill>/scripts/_vendor/config.py``, FOUR levels below it. A fixed
    parent count is therefore wrong in one of them by construction — it used to
    resolve to ``skills/<skill>/`` in every vendored copy, so ``EXAMPLE_CONFIG``
    named a file that cannot exist and every "am I on the fictional example?"
    comparison against it answered a constant "no". The upward walk answers
    correctly from both homes, and it is also what
    ``docs/handbook/skills-and-vendoring.md`` requires: a skill folder dropped into
    ANOTHER project has to find that host project's root.

    Markers, in order of authority:
      1. ``.git`` — the definitive project boundary (see ``_git_boundary``).
      2. ``config.example.yaml`` — this toolkit's own tracked root marker, used
         only when there is no ``.git`` at all (a source zip/tarball export).
         Without it a ``.git``-less download would lose the example fallback.

    Neither marker present — a skill folder unpacked outside any project — the
    answer is the module's OWN directory. It is the only candidate guaranteed to
    exist and guaranteed to stay INSIDE the unpacked artifact; walking further up
    could reach an unrelated ``/private`` (a real directory on macOS) and refuse
    the fallback, or adopt a stranger's ``config.example.yaml``. ``EXAMPLE_CONFIG``
    then names a file that does not exist, which is the honest answer: with no
    project tree there is no tracked example persona, so the fallback is inert.
    """
    boundary = _git_boundary(start)
    if boundary is not None:
        return boundary
    for parent in (start, *start.parents):
        if (parent / EXAMPLE_CONFIG_FILENAME).exists():
            return parent
    return start


# Derived from THIS file's location by the upward walk above — NOT by counting
# parents — so the canonical module and all four vendored copies agree on it.
REPO_ROOT = _repo_root(_HERE)
EXAMPLE_CONFIG = REPO_ROOT / EXAMPLE_CONFIG_FILENAME


class ConfigError(RuntimeError):
    """The active config file exists but cannot be used (e.g. malformed YAML)."""


class ConfigNotFound(ConfigError):
    """No real ``config.yaml`` is reachable and the example fallback is refused.

    Raised when discovery would silently point the toolkit at the fictional
    "Jordan Rivers" example while real data is present (a ``private/`` overlay is
    mounted), or when ``$JOBHUNT_REQUIRE_REAL_CONFIG`` forbids the fallback.
    """


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() not in _FALSEY


def _search_up(start: Path) -> tuple[Path | None, Path | None]:
    """Walk up from ``start`` for ``config.yaml``, stopping at the git boundary.

    Returns ``(config_path_or_None, boundary_dir_or_None)``. The boundary is the
    first directory holding a ``.git`` entry; it IS searched for a config before
    the walk stops there, and it is reported only when no config was found (it is
    then the repo root used for the overlay check).
    """
    boundary = _git_boundary(start)
    for parent in (start, *start.parents):
        candidate = parent / CONFIG_FILENAME
        if candidate.exists():
            return candidate, None
        if parent == boundary:
            break
    return None, boundary


def _refuse_example_fallback(boundaries: list[Path]) -> str | None:
    """Return the reason the example fallback is refused, or None if it is allowed."""
    if _truthy_env(REQUIRE_REAL_CONFIG_ENV_VAR):
        return f"${REQUIRE_REAL_CONFIG_ENV_VAR} is set"
    for root in boundaries or [REPO_ROOT]:
        overlay = root / OVERLAY_DIRNAME
        if overlay.is_dir():
            return f"a private overlay is mounted at {overlay}"
    return None


def _searched_description() -> str:
    return (f"{CONFIG_FILENAME} searched upward from {Path.cwd()} and from {_HERE} "
            f"(stopping at the nearest {_GIT_MARKER} boundary); "
            f"${ENV_VAR} is unset or names a missing file")


def _discover_config() -> tuple[Path, bool]:
    """Locate the active config file. Returns ``(path, used_example_fallback)``."""
    # 1. Explicit path from the environment.
    env = os.environ.get(ENV_VAR)
    if env:
        p = Path(env).expanduser()
        if p.exists():
            return p, False
    # 2. Nearest config.yaml walking up from cwd, then from this file's directory,
    #    each walk stopping at its repository boundary.
    boundaries: list[Path] = []
    for start in (Path.cwd(), _HERE):
        found, boundary = _search_up(start)
        if found is not None:
            return found, False
        if boundary is not None and boundary not in boundaries:
            boundaries.append(boundary)
    # 3. Fallback to the tracked example config — unless that would silently run
    #    the toolkit on the fictional persona while real data is on disk.
    reason = _refuse_example_fallback(boundaries)
    if reason is not None:
        raise ConfigNotFound(
            f"No {CONFIG_FILENAME} found and the fictional example config "
            f"({EXAMPLE_CONFIG}) was refused because {reason}. "
            f"{_searched_description()}. "
            f"Set ${ENV_VAR}=/path/to/{CONFIG_FILENAME}, or run from a directory "
            f"inside the checkout that holds it.")
    return EXAMPLE_CONFIG, True


def _find_config_path() -> Path:
    """Locate the active config file per the documented discovery order."""
    return _discover_config()[0]


@lru_cache(maxsize=1)
def _load() -> tuple[Path, dict]:
    """Return (config_path, config_dict), cached for the process lifetime.

    The example-fallback notice is printed HERE (not in discovery) so it fires
    once per process rather than once per accessor call.
    """
    path, used_example = _discover_config()
    if used_example:
        print(f"config: no {CONFIG_FILENAME} found — using the fictional example "
              f"persona at {path}. {_searched_description()}.", file=sys.stderr)
    try:
        text = path.read_text()
    except OSError as exc:
        # A missing/unreadable file keeps the historical empty-config behaviour —
        # discovery above already decided whether that is acceptable — but it says
        # so, because "every value silently fell back to its default" is exactly
        # the state that must never look like a successful load.
        print(f"config: {path} could not be read ({exc}); continuing with an EMPTY "
              f"configuration — every value falls back to its default.",
              file=sys.stderr)
        return path, {}
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(
            f"{path} must contain a YAML mapping at the top level, "
            f"got {type(data).__name__}")
    return path, data


def config_path() -> Path:
    """Absolute path of the config file that was loaded."""
    return _load()[0]


def _config() -> dict:
    return _load()[1]


def _config_dir() -> Path:
    return _load()[0].parent


# ── candidate identity ───────────────────────────────────────
def _candidate() -> dict:
    return _config().get("candidate") or {}


def candidate_name() -> str:
    return str(_candidate().get("name", ""))


def contact_line() -> str:
    return str(_candidate().get("contact_line", ""))


def name_slug() -> str:
    return str(_candidate().get("name_slug", ""))


def title_slug() -> str:
    return str(_candidate().get("title_slug", ""))


# ── output filename stems (composed from the identity slugs) ──
def resume_stem(label: str = "") -> str:
    """Rendered-resume output stem, with an optional target-position suffix."""
    return layout.compose_stem(f"{name_slug()}_{title_slug()}_Resume", label)


def cover_stem(label: str = "") -> str:
    """Cover-letter output stem, with an optional target-position suffix."""
    return layout.compose_stem(f"{name_slug()}_Cover_Letter", label)


def application_stem(label: str = "") -> str:
    """Bundled application .txt stem, with an optional target-position suffix."""
    return layout.compose_stem(f"{name_slug()}_{title_slug()}_Application", label)


# ── paths (resolved relative to the config file's directory) ──
def _paths() -> dict:
    return _config().get("paths") or {}


def _resolve(value: str | None, default: str) -> Path:
    """Resolve a config-relative path (or default) to an absolute Path."""
    p = Path(value or default)
    if p.is_absolute():
        return p
    return (_config_dir() / p).resolve()


def _resolve_configured(key: str, derived: Path) -> Path:
    """``paths.<key>`` resolved like every other path, else the ``derived`` default.

    Keeps each "where does X live" answer a single knob: an explicit config key
    when the layout is non-standard, otherwise a derivation from the two roots
    (``applications_root`` / ``overlay_root``) that never appears as a literal in
    a consumer script.
    """
    configured = _paths().get(key)
    if configured:
        return _resolve(str(configured), "")
    return derived


def profile_md_path() -> Path:
    return _resolve(_paths().get("profile_md"),
                    "examples/me/career/profile.example.md")


def baseline_path() -> Path:
    # Baseline follows the same public-fixture fallback as profile/reference, not
    # candidate_dir(): real and benchmark configs set it explicitly as a read-only
    # candidate source, while a config-less public clone must load fictional data.
    return _resolve(_paths().get("baseline_yaml"),
                    "examples/me/career/resume/baseline.example.yaml")


def reference_docx_path() -> Path:
    return _resolve(_paths().get("reference_docx"),
                    "examples/me/career/resume/reference.example.docx")


def company_levels_path() -> Path:
    """Reusable company-level/compensation cache.

    Real job hunts keep this beside the candidate profile by default so dated
    compensation research remains private. The tracked example config points to
    a fictional example cache explicitly.
    """
    configured = _paths().get("company_levels_yaml")
    if configured:
        # No default literal: ``_resolve`` only reads its second argument when the
        # first is falsy, so a default written here is unreachable by construction.
        return _resolve(str(configured), "")
    # Derived from candidate_dir(), NOT from the profile's parent. Both resolve to
    # the same folder in a default layout, but the person-first taxonomy moves the
    # profile to ``me/career/`` while this file belongs with the market logs — and riding
    # on ``profile_md_path().parent`` would silently follow the profile there.
    return candidate_dir() / "company-levels.yaml"


def applications_root() -> Path:
    return _resolve(_paths().get("applications_root"), "applications")


def discoveries_dir() -> Path:
    return _resolve(_paths().get("discoveries_dir"), "applications/1_discoveries")


# The candidate/profile support folder inside the applications root. It is NOT a
# status folder (see layout.STATUS_DIRS); it holds the profile, the baseline, the
# tailoring card, and the skip-logs. These names are module CONSTANTS (no config
# load) so a caller driving an explicit tree — e.g. handoff.py's
# ``--applications-root`` override, which must work with no config at all — can
# compose the same layout without re-hardcoding a literal.
CANDIDATE_DIRNAME = "0_profile"
TAILORING_CARD_FILENAME = "tailoring-card.md"
APPLICATIONS_LOG_FILENAME = "applications-log.yaml"
APPLICATIONS_JSONL_FILENAME = "applications-log.jsonl"
COMPANY_SEARCH_LOG_FILENAME = "company-search-log.yaml"
CALENDAR_FILENAME = "calendar.md"


def overlay_root() -> Path:
    """Root of the private overlay tree (``private/`` in a real deployment).

    Everything candidate-specific that is NOT an application lives under it:
    the blacklist, the story bank, search profiles, per-skill private references,
    the company cache. Defaults to the parent of ``applications_root``. Benchmark
    configs rely on that derivation to isolate overlay-relative paths beside their
    redirected applications tree. A live person-first layout with applications at
    ``private/me/applications`` must set ``paths.overlay_root: private`` explicitly,
    because its applications root is not an immediate child of the overlay.
    """
    return _resolve_configured("overlay_root", applications_root().parent)


def candidate_dir() -> Path:
    """The candidate support folder: ``<applications_root>/0_profile``.

    Holds the tailoring card, the skip-logs, the calendar, and (by convention)
    the profile + baseline. Override with ``paths.candidate_dir``.
    """
    return _resolve_configured("candidate_dir", applications_root() / CANDIDATE_DIRNAME)


# These three used to be hard-derived as ``candidate_dir() / <FILENAME>`` with no
# key of their own, which was fine while all three lived in one folder. The
# person-first taxonomy sends the card to ``me/career/`` and the logs to
# ``market/logs/``, and one ``candidate_dir`` cannot express that — so each gets a
# key.
#
# The DEFAULT stays the old derivation, and that is load-bearing rather than
# conservative. ``config.benchmark.yaml`` isolates benchmark writes SOLELY by
# redirecting ``applications_root`` and letting ``candidate_dir()`` follow. Derive
# these from a new ``me``/``market`` root instead and a benchmark run resolves the
# REAL tailoring card and the REAL skip-log — and writes to them. A contaminated
# skip-log is silent and durable: it suppresses real applications from then on.
def tailoring_card_path() -> Path:
    """The distilled tailoring card (derived artifact; see the resume-writer skill)."""
    return _resolve_configured("tailoring_card",
                               candidate_dir() / TAILORING_CARD_FILENAME)


def applications_log_path() -> Path:
    """Skip-log of postings already generated/considered (derived, regenerable)."""
    return _resolve_configured("applications_log",
                               candidate_dir() / APPLICATIONS_LOG_FILENAME)


def applications_jsonl_path() -> Path:
    """Append-only event log of postings already generated/considered.

    The same skip-log as ``applications_log_path()`` in a format nothing
    regenerates: one JSON object per line, folded last-wins, never rewritten. That
    is what stops a deleted application folder from un-skipping its posting — and
    it also removes the safety net the comment above describes. A benchmark run
    that resolved the REAL skip-log used to be self-healing, because the next
    ``--sync-log`` regenerated the whole file from the real folders and washed the
    fixture rows out. Here there is no regeneration: a contaminated line is
    permanent and silently suppresses a real posting forever. So the default rides
    ``candidate_dir()`` — the one knob ``config.benchmark.yaml`` turns — rather
    than ``applications_log_path().parent``, which would isolate only by accident.
    """
    return _resolve_configured("applications_jsonl",
                               candidate_dir() / APPLICATIONS_JSONL_FILENAME)


def company_search_log_path() -> Path:
    """Skip-log of each employer's last SUCCESSFUL search."""
    return _resolve_configured("company_search_log",
                               candidate_dir() / COMPANY_SEARCH_LOG_FILENAME)


def blacklist_path() -> Path:
    """Candidate blacklist overlay merged into the public company registry.

    Defaults to ``<overlay_root>/market/blacklist.yaml``; override with
    ``paths.blacklist_yaml``. Personal skip rules never live in the public
    ``skills/job-search/companies.yaml``.
    """
    return _resolve_configured(
        "blacklist_yaml", overlay_root() / "market" / "blacklist.yaml")


def story_bank_path() -> Path:
    """Behavioral story bank directory (may not exist; callers degrade gracefully).

    Defaults to ``<overlay_root>/me/interviews/story-bank``; override with
    ``paths.story_bank_dir``. Both the tailoring-card builder and the gardener's
    staleness check hash this directory, so they MUST agree on it byte for byte —
    which is why they read this accessor rather than re-deriving the path, and why
    their ``STORY_BANK_REL`` display constant tracks the same layout.
    """
    return _resolve_configured(
        "story_bank_dir", overlay_root() / "me" / "interviews" / "story-bank")


def search_profiles_dir() -> Path:
    """Candidate job-search profiles.

    Defaults to ``<overlay_root>/market/searches``; override with
    ``paths.search_profiles_dir``.
    """
    return _resolve_configured(
        "search_profiles_dir", overlay_root() / "market" / "searches")


def skill_references_dir(skill: str) -> Path:
    """Per-skill private reference folder for candidate-specific skill guidance.

    Defaults to ``<overlay_root>/skills/skill-notes/<skill>``; override the root with
    ``paths.skill_references_root``. Never tracked in the public tree — the leak guard
    fails on any tracked file under a ``skill-notes/`` folder (or under the folder's
    retired name, ``references_private/``; see
    ``automation/publish/check_public.SKILL_NOTES_DIRNAMES``).
    """
    root = _resolve_configured(
        "skill_references_root", overlay_root() / "skills" / "skill-notes")
    return root / skill


def companies_root() -> Path:
    """Company-specific interview-prep tree.

    Defaults to ``<overlay_root>/me/interviews/companies``; override with
    ``paths.companies_root``.
    """
    return _resolve_configured(
        "companies_root", overlay_root() / "me" / "interviews" / "companies")


def overlay_mounted() -> bool:
    """True when a private overlay tree is actually mounted.

    An overlay is "mounted" when ``overlay_root()`` is an existing directory that
    is distinct from the config file's own directory. In a fresh public clone the
    derivation collapses onto the repo root (which is also the config dir), which
    is exactly the "no overlay" case: callers use this to stay silent about
    missing personal files that a public checkout is never expected to have.
    """
    root = overlay_root()
    # overlay_root() is fully resolved; _config_dir() is not (it is the config path
    # as discovered), so compare resolved forms or a symlinked prefix — /var vs
    # /private/var on macOS — reads as "distinct" and reports a phantom overlay.
    return root.is_dir() and root != _config_dir().resolve()


def calendar_path() -> Path:
    """The single private calendar/todo file (``calendar.md``).

    Defaults to ``<candidate_dir>/calendar.md`` so a real configuration resolves
    into the private overlay while the tracked example config resolves into the
    fictional ``examples/`` tree. Override with ``paths.calendar_md``.
    """
    return _resolve_configured("calendar_md", candidate_dir() / CALENDAR_FILENAME)


# ── raw-data-layer store root ─────────────────────────────────
DATA_ROOT_ENV_VAR = "JOBHUNT_DATA_ROOT"


def data_root() -> Path | None:
    """Root of the raw-data-layer store, or ``None`` when the store is DISABLED.

    Discovery order: the ``JOBHUNT_DATA_ROOT`` env var wins; then a ``paths.data_root``
    config value (resolved relative to the config file like every other path). When
    neither is set the store is disabled — capture no-ops and the query/validate
    tools print a clear "store not configured" message. There is deliberately NO
    default (unlike the other paths): the store must never write into a tracked dir,
    so CI and the example config leave ``data_root`` unset.
    """
    env = os.environ.get(DATA_ROOT_ENV_VAR)
    if env:
        return Path(env).expanduser().resolve()
    configured = _paths().get("data_root")
    if configured:
        p = Path(configured).expanduser()
        if p.is_absolute():
            return p.resolve()
        return (_config_dir() / p).resolve()
    return None


# ── job-search + location policy ─────────────────────────────
def default_profile() -> str:
    js = _config().get("job_search") or {}
    return str(js.get("default_profile", "default"))


def location_policy() -> dict:
    """The location-matching policy for location.py's classifiers.

    Returns a dict with ``metro`` / ``remote_tokens`` / ``us_remote_regions`` lists
    (``None`` when the config omits an optional key so location.py falls back to its
    module defaults) plus the ``allow_us_remote`` / ``us_only`` booleans (defaulting
    to True).
    """
    lp = _config().get("location_policy") or {}

    def _list(key):
        val = lp.get(key)
        return list(val) if val else None

    return {
        "metro": _list("metro"),
        "remote_tokens": _list("remote_tokens"),
        "us_remote_regions": _list("us_remote_regions"),
        "allow_us_remote": lp.get("allow_us_remote", True),
        "us_only": lp.get("us_only", True),
    }


# ── leak guard ────────────────────────────────────────────────
def leak_guard_english_word_tokens() -> list[str]:
    """Identity tokens the owner declares to be ordinary ENGLISH WORDS.

    Read by the publish leak guard (``automation/publish/check_public.py``). A
    surname such as Green, Long, Park or Quick is both an identity token and a
    word this repository's own prose uses constantly, and no boundary rule can
    tell "Menlo Park" from "Alex Park". Naming one here reduces the guard's
    protection for that ONE bare word — and only for it: the owner's email,
    handles, home-directory basename and every derived name compound
    (``alexgreen``, ``alex-green``, ``agreen``) keep full protection, so the
    full name written any way at all is still caught.

    OPT-IN, never inferred. The guard prints every declared word and the number
    of occurrences it skipped on every single run, so the reduction can never be
    silently in effect. Declared as::

        leak_guard:
          english_word_tokens: ["Green"]

    Absent / empty is the normal state and the default.
    """
    block = _config().get("leak_guard") or {}
    raw = block.get("english_word_tokens") or []
    if isinstance(raw, str):
        raw = [raw]
    return [str(word).strip() for word in raw if str(word).strip()]


# ── generation mode (token_saving default | full) ────────────
def generation_mode() -> str:
    """Token-usage mode for search + drafting: ``token_saving`` (default) or ``full``.

    An absent ``generation`` section or ``mode`` key resolves to ``token_saving``.
    The mode scales how much *context and iteration* a routine run spends (research
    depth, render/polish cycles, up-front library reads, extra sweeps); it never
    relaxes a hard gate or validator — those run identically in both modes.
    """
    gen = _config().get("generation") or {}
    return str(gen.get("mode", "token_saving"))


# ── Outlook email assistant ───────────────────────────────────
def outlook_email_config() -> dict:
    """Personal-Outlook OAuth configuration for the draft-only email skill.

    The client ID is an identifier, not a client secret. Refresh tokens never
    belong in this config; the skill stores OAuth refresh state in the OS keyring.
    Restricting the authority to ``consumers`` prevents an accidental work-
    tenant login when this toolkit is configured for a personal mailbox.
    """
    mail = _config().get("outlook_email") or {}
    return {
        "account": str(mail.get("account", "")).strip(),
        "client_id": str(mail.get("client_id", "")).strip(),
        "tenant": str(mail.get("tenant", "consumers")).strip() or "consumers",
    }


def outlook_email_review_config() -> dict:
    """Optional private context for a content-free local email-store review.

    ``company_domains`` maps a company name to one or more non-ATS mail
    domains.  A larger mapping may instead live in ``company_domains_path``;
    its YAML top level uses the same mapping shape.  Neither setting is needed
    for synchronization, and neither is ever printed by the email CLI.
    """
    mail = _config().get("outlook_email") or {}
    configured_domains = mail.get("company_domains") or {}
    configured_path = mail.get("company_domains_path")
    path = None
    if isinstance(configured_path, str) and configured_path.strip():
        path = _resolve(configured_path.strip(), "private/email-company-domains.yaml")
    return {
        "company_domains": configured_domains,
        "company_domains_path": path,
    }
