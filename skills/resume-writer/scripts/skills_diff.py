"""Print the Step-7 uncategorized-skill queue for a job description.

Extracts the concrete skill/technology phrases a JD mentions and reports only
those the candidate profile has NOT categorized — i.e. verbatim JD phrases that
are in none of the profile's Approved / Weak / Never lists. The agent then just
presents the queue and runs the batched Step-7 categorization protocol; it no
longer has to extract + diff skills in-context.

Queue membership reuses check.py's OWN skill-list parser and matching helpers by
sibling import, so it matches the render gate EXACTLY — including alias handling
and the component-wise Weak-token match (a JD "REST APIs" is covered by a Weak
"REST/gRPC APIs" and is therefore NOT queued).

Every queued item becomes a BLOCKING question to the user (Step 7 asks them to
categorize it), so this report is precision-first in three further ways:
  * a JD's provenance URL, its query keys and its location / time-zone metadata
    are removed before extraction — "includeCompensation" and "ET" are not
    skills and must never become user decisions;
  * a compound is one concept: "CI/CD" and "A/B testing" are asked once, never
    split into "CI" + "CD" or duplicated as "A/B" + "A/B-testing";
  * a qualified profile entry categorizes its concept, so "Java basics" answers
    a JD's "Java" and "MySQL administration" answers "MySQL". That is a matching
    rule for THIS report only — it never edits the profile and never broadens a
    claim; check.py still decides what a resume may say.

Usage:
    python skills/resume-writer/scripts/skills_diff.py <JD-file.md>
    python skills/resume-writer/scripts/skills_diff.py applications/6_drafted/<slug>/
    python skills/resume-writer/scripts/skills_diff.py <JD-file.md> --profile <profile.md>

The profile defaults to config.profile_md_path(). Exit code is always 0 (this is
a report, not a gate); an empty queue prints "no uncategorized skills".
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Self-contained skill: put the scripts/ folder and its _vendor/ on sys.path so
# `import check` (sibling) and `import config` / `from layout import ...` (vendored)
# all resolve, exactly like check.py does.
_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE / "_vendor"):
    if str(_p) not in sys.path and _p.is_dir():
        sys.path.insert(0, str(_p))

import check  # sibling — reuse its skill-list parser + matching helpers (no copies)
import config
from layout import find_jd_files

# ── Skill-phrase extraction (heuristic; precision-first) ──────────────────────
# The queue only matters when a phrase is NOT already categorized, so a false
# POSITIVE (flagging a company name / header word as an uncategorized skill) is
# the failure to avoid. A candidate is therefore recognized only when it carries
# a real technology signal: a structural signal (camelCase like "PostgreSQL" /
# "OpenTelemetry", or tech punctuation with a capital like "CI/CD" / "C++"), a
# proper-noun match against the known-tech lexicon (capitalized in the JD), a
# lowercase technical concept, or a multiword lexicon phrase. Bare capitalized
# words ("Example Corp"), acronyms ("SRE", "APIs"), and English words are not
# recognized. Recall is best-effort — the gate stays authoritative.
MAX_PHRASE_WORDS = 4

# Common technology proper nouns (lowercased). Recognized only when the JD spells
# them with a capital, so English collisions ("go to market", "spring cleaning")
# are not flagged. Not the source of truth — a recall aid; the profile lists +
# check.py matching decide membership.
KNOWN_TECH = frozenset({
    # languages
    "python", "java", "go", "golang", "javascript", "typescript", "ruby", "rust",
    "scala", "kotlin", "elixir", "swift", "php", "perl", "c", "c++", "c#", "r",
    "sql", "bash", "clojure", "haskell", "dart", "lua", "groovy", "objective-c",
    # runtimes / frameworks
    "node", "node.js", "nodejs", "react", "angular", "vue", "svelte", "next.js",
    "django", "flask", "fastapi", "rails", "spring", "express", "laravel",
    ".net", "asp.net", "hibernate", "tailwind", "graphql", "grpc",
    # infra / devops / observability
    "docker", "kubernetes", "k8s", "terraform", "ansible", "puppet", "chef",
    "helm", "nginx", "envoy", "istio", "consul", "vault", "packer", "argocd",
    "jenkins", "gitlab", "circleci", "bazel", "webpack", "vite", "prometheus",
    "grafana", "datadog", "splunk", "sentry", "opentelemetry", "jaeger", "kibana",
    # cloud
    "aws", "gcp", "azure", "ec2", "s3", "lambda", "sqs", "sns", "dynamodb", "rds",
    "eks", "ecs", "fargate", "cloudformation", "bigquery", "redshift", "athena",
    # data / db / streaming
    "postgresql", "postgres", "mysql", "mariadb", "sqlite", "mongodb", "redis",
    "cassandra", "elasticsearch", "opensearch", "clickhouse", "cockroachdb",
    "neo4j", "kafka", "rabbitmq", "pulsar", "nats", "spark", "hadoop", "hive",
    "flink", "airflow", "dbt", "snowflake", "databricks", "presto", "trino",
    # ml / ai
    "pytorch", "tensorflow", "keras", "scikit-learn", "numpy", "pandas", "jax",
    "langchain", "onnx",
    # web / api / protocols
    "rest", "soap", "websockets", "webrtc", "oauth", "openapi", "swagger",
    "protobuf", "webassembly", "wasm",
    # tools / collab
    "git", "github", "bitbucket", "jira", "confluence", "linux", "unix",
    # multiword / compound phrases — these are ONE concept and are never split
    "rest api", "rest apis", "graphql api", "distributed systems",
    "event-driven architecture", "message queue", "message queues", "ci/cd",
    "machine learning", "deep learning", "data pipeline", "data pipelines",
    "service mesh", "infrastructure as code", "infrastructure-as-code",
    "github actions", "spring boot", "hugging face", "scikit learn",
    "a/b", "a/b testing", "ui/ux",
})

# Tokens that are never a skill in any casing. Time-zone and region codes reach
# the extractor through a JD's logistics text ("9am-5pm ET/PT"), and generic
# section words reach it through headers ("WEB/mobile"); both then arrive at the
# user as a BLOCKING categorization question about something that is not a
# skill at all (issue #261). Kept small and unambiguous on purpose — a token
# here can never be queued, so nothing that could plausibly be a technology
# belongs in it.
NON_SKILL_TOKENS = frozenset({
    # time zones
    "et", "pt", "ct", "mt", "est", "edt", "cst", "cdt", "mst", "mdt", "pst",
    "pdt", "akst", "hst", "utc", "gmt", "bst", "cet", "cest", "eet", "ist",
    "jst", "kst", "sgt", "aest", "aedt", "nzst",
    # regions / work-arrangement words
    "us", "usa", "eu", "uk", "emea", "apac", "latam", "amer", "noram",
    "remote", "hybrid", "onsite", "on-site", "wfh",
    # generic section / header words
    "web", "mobile", "desktop", "office", "team", "teams", "role", "roles",
    "full-time", "part-time", "fte", "ic", "eng", "tech",
})

# Postal abbreviations, used ONLY to recognize a "City, ST" pair. They are not
# blocklisted globally: "AR", "IN" and "OR" are real words/technologies outside
# an address, and this tool must not suppress those.
_US_STATES = (
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS "
    "MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV "
    "WI WY DC PR"
).split()

# Provenance URLs (a saved JD records where it came from) carry camelCase query
# keys — "?includeCompensation=true" — which look exactly like a technology
# token to the structural test below. Strip the URL, its query string, and any
# stray "key=value" fragment before extraction.
_URL_RE = re.compile(
    r"(?:https?://|www\.)\S+"
    # A bare host is stripped only WITH a path or query, so a dotted technology
    # name ("socket.io", "next.js") is never mistaken for a link.
    r"|\b[\w-]+(?:\.[\w-]+)*\.(?:com|org|net|io|ai|co|dev|app|edu|gov|jobs|careers)"
    r"(?:/\S*|\?\S*)",
    re.I)
_QUERY_FRAGMENT_RE = re.compile(r"[?&][A-Za-z0-9_.-]+=[^\s&]*")
# A labelled logistics field says where and when the job is worked, never what
# it is built with, so its VALUE is dropped: the addresses and time zones go
# with it. Only up to the next segment separator, so a one-line header such as
# "Location: NYC | Stack: Go, Kubernetes" keeps the half that names the stack.
_META_FIELD_RE = re.compile(
    r"^\s*(?:[-*+•>]\s*)?[*_#\s]*"
    r"(?:locations?|offices?|work location|workplace|time\s*-?\s*zones?|"
    r"(?:core |working |work )?hours|source|url|link|apply|posted|"
    r"job id|req(?:uisition)? id|salary|compensation|pay(?: range)?)"
    r"[*_\s]*:[^|•·]*",
    re.I)
_CITY_STATE_RE = re.compile(
    r"\b[A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,3},\s*(?:%s)\b" % "|".join(_US_STATES))

# Inherently-lowercase technical concepts recognized without a capital.
LOWERCASE_CONCEPTS = frozenset({
    "microservices", "observability", "serverless", "containerization",
    "virtualization", "middleware", "sharding", "autoscaling", "caching",
    "socket.io",
})

# A token is a maximal run of alphanumerics plus internal tech punctuation.
_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9+.#/-]*")
_CAMEL_RE = re.compile(r"[a-z][A-Z]")
_PUNCT_TECH_RE = re.compile(r"[/+#]")
_DEGREE_CHAIN_RE = re.compile(
    r"^(?:B(?:A|S)|M(?:A|S)|PhD)(?:/(?:B(?:A|S)|M(?:A|S)|PhD))*$",
    re.I,
)


# Words that QUALIFY a skill rather than name one. A profile entry such as
# "Java basics" / "basic SQL queries" / "MySQL administration" is already a
# truthful, deliberate decision about that concept, so the bare JD token must
# not be queued again: asking a second time pressures the user into adding a
# broader, less truthful duplicate entry (issue #272). Matching on the stripped
# concept never rewrites the profile — the qualifier stays exactly as written,
# and check.py remains the authority on what a resume may claim.
_QUALIFIER_WORDS = frozenset({
    "basic", "basics", "beginner", "intro", "introductory", "fundamentals",
    "familiarity", "exposure", "experience", "knowledge", "background",
    "work", "working", "usage", "use", "using", "hands-on", "light", "some",
    "limited", "advanced", "expert", "expertise", "proficiency", "proficient",
    "skills", "skill", "administration", "admin", "development", "testing",
    "queries", "query", "scripting", "programming", "coding", "level",
})


def _phrase_key(tokens: list[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(tokens)).strip().lower()


def _concept_key(phrase: str) -> str:
    """The bare concept a phrase names, with qualifiers and separators removed.

    ``A/B-testing``, ``A/B testing`` and ``A/B`` all name one concept, and so do
    ``MySQL`` and ``MySQL administration``. Used for MATCHING and de-duplication
    only — the queue always prints the JD's verbatim phrasing.
    """
    key = check._skill_key(phrase).replace("-", " ")
    words = [w for w in re.split(r"\s+", key) if w]
    while words and words[0] in _QUALIFIER_WORDS:
        words.pop(0)
    while words and words[-1] in _QUALIFIER_WORDS:
        words.pop()
    return " ".join(words) if words else key


def _concept_keys(entry: str) -> set[str]:
    """Concept keys for one profile entry, including its nested members."""
    return {c for c in (_concept_key(k) for k in check._skill_keys(entry)) if c}


def _strip_metadata(jd_text: str) -> str:
    """Drop provenance URLs and location/time-zone metadata before extraction."""
    lines = []
    for line in jd_text.splitlines():
        line = _META_FIELD_RE.sub(" ", line, count=1)
        line = _URL_RE.sub(" ", line)
        line = _QUERY_FRAGMENT_RE.sub(" ", line)
        line = _CITY_STATE_RE.sub(" ", line)
        lines.append(line)
    return "\n".join(lines)


def _is_structural(token: str) -> bool:
    """Token carries a structural technology signal (camelCase or tech punct)."""
    if _CAMEL_RE.search(token):
        return True
    # Tech punctuation only counts with an uppercase letter, so "and/or" is out
    # while "CI/CD", "C++", "REST/gRPC" are in.
    return bool(_PUNCT_TECH_RE.search(token) and re.search(r"[A-Z]", token))


def _single_token_counts(token: str) -> bool:
    key = token.lower().strip(".")
    if _DEGREE_CHAIN_RE.fullmatch(token.replace(".", "")):
        return False
    if key in NON_SKILL_TOKENS:
        return False
    if key in LOWERCASE_CONCEPTS:
        return True
    if key in KNOWN_TECH and re.search(r"[A-Z]", token):
        return True
    return _is_structural(token)


def _is_known_compound(phrase: str) -> bool:
    """True when the whole compound is itself a known concept ("CI/CD", "A/B")."""
    return (check._skill_key(phrase) in KNOWN_TECH
            or _concept_key(phrase) in KNOWN_TECH)


def _compound_components(phrase: str) -> list[str]:
    """Return skill-like slash components, excluding plain English fragments."""
    if "/" not in phrase:
        return []
    parts = [part.strip() for part in phrase.split("/") if part.strip()]
    if len(parts) < 2:
        return []
    return [
        part for part in parts
        if part.lower() not in NON_SKILL_TOKENS
        and (_single_token_counts(part) or (part.isupper() and len(part) >= 2))
    ]


def extract_skill_phrases(jd_text: str) -> list[str]:
    """Verbatim skill phrases in first-seen order, deduped by normalized key."""
    jd_text = _strip_metadata(jd_text)
    # Strip trailing/leading sentence punctuation (".", "/", "-") so "Kubernetes."
    # and "APIs." normalize to their token; "+"/"#" are kept for "C++"/"C#".
    words = [w for w in (m.group(0).strip("./-") for m in _WORD_RE.finditer(jd_text)) if w]
    out: list[str] = []
    seen: set[str] = set()

    def _record(phrase: str):
        key = check._skill_key(phrase)
        if key and key not in seen:
            seen.add(key)
            out.append(phrase)

    i = 0
    n = len(words)
    while i < n:
        matched = False
        # Greedy longest multiword lexicon phrase first.
        for length in range(min(MAX_PHRASE_WORDS, n - i), 1, -1):
            span = words[i:i + length]
            if _phrase_key(span) in KNOWN_TECH:
                _record(" ".join(span))
                i += length
                matched = True
                break
        if matched:
            continue
        if _single_token_counts(words[i]):
            _record(words[i])
        i += 1
    return out


def uncategorized_queue(jd_text: str, profile_text: str) -> list[str]:
    """Skill phrases in the JD that no profile list categorizes (gate-exact)."""
    approved, weak, never = check.parse_skill_lists(profile_text)
    profile_concepts = {
        concept
        for entries in (approved, weak, never)
        for entry in entries
        for concept in _concept_keys(entry)
    }

    def _categorized(phrase: str) -> bool:
        # Direct membership (exact + aliases + nested AWS(...) expansion) …
        if (check._in_list(phrase, approved)
                or check._in_list(phrase, weak)
                or check._in_list(phrase, never)):
            return True
        # Store one-letter programming languages with an explicit "language"
        # suffix: a bare Never token such as "C" can over-match unrelated
        # resume text, but a JD's standalone "C" / "R" still belongs to that
        # category and should not be re-queued.
        if len(phrase) == 1 and phrase.isalpha():
            language = f"{phrase} language"
            if (check._in_list(language, approved)
                    or check._in_list(language, weak)
                    or check._in_list(language, never)):
                return True
        # A profile can suppress an extractor false positive without globally
        # blocklisting the underlying word in valid resume prose/contact data.
        # Example: "LinkedIn non-skill" keeps the company name out of this
        # queue without making linkedin.com violate the Never gate.
        if check._in_list(f"{phrase} non-skill", never):
            return True
        # A qualified profile entry already categorizes its concept: "Java
        # basics" covers a JD's "Java", "MySQL administration" covers "MySQL",
        # and "CI/CD work" covers "CI/CD". Re-asking would only produce a
        # broader duplicate entry (issue #272).
        if _concept_key(phrase) in profile_concepts:
            return True
        # … plus the component-wise Weak semantics the gate uses: a Weak token
        # like "REST/gRPC APIs" is satisfied by a JD "REST APIs".
        return any(check._mentioned_in_jd(w, phrase) for w in weak)

    queue: list[str] = []
    seen: set[str] = set()
    for phrase in extract_skill_phrases(jd_text):
        if _categorized(phrase):
            continue
        if _is_known_compound(phrase):
            # "CI/CD" and "A/B testing" are one concept — never two questions.
            candidates = [phrase]
        elif "/" in phrase:
            candidates = _compound_components(phrase)
            if not candidates:
                # No component is a skill ("WEB/mobile", "ET/PT") — not an ask.
                continue
        else:
            candidates = [phrase]
        for candidate in candidates:
            # De-duplicate by concept so "A/B", "A/B-testing" and "A/B testing"
            # become ONE categorization question, in the JD's own phrasing.
            key = _concept_key(candidate) or check._skill_key(candidate)
            if key and key not in seen and not _categorized(candidate):
                seen.add(key)
                queue.append(candidate)
    return queue


def _read_jd_text(target: Path) -> str:
    if target.is_dir():
        jd_files = find_jd_files(target)
        if not jd_files:
            raise SystemExit(f"No JD-*.md files found under {target}")
        return "\n\n".join(p.read_text(encoding="utf-8") for p in jd_files)
    return target.read_text(encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Print the Step-7 uncategorized-skill queue for a JD")
    parser.add_argument("jd", help="JD-*.md file, or an application folder")
    parser.add_argument("--profile", default=None,
                        help="Profile markdown (default: config.profile_md_path())")
    args = parser.parse_args(argv)

    jd_text = _read_jd_text(Path(args.jd))
    profile_path = Path(args.profile) if args.profile else config.profile_md_path()
    profile_text = profile_path.read_text(encoding="utf-8")

    queue = uncategorized_queue(jd_text, profile_text)
    if not queue:
        print("no uncategorized skills")
        return 0
    for phrase in queue:
        print(phrase)
    print(f"— {len(queue)} uncategorized skill(s): in none of the profile's "
          "Approved/Weak/Never lists. Categorize with the user (Step 7); never add silently.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
