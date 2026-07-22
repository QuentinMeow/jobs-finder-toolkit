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
    # multiword phrases
    "rest api", "rest apis", "graphql api", "distributed systems",
    "event-driven architecture", "message queue", "message queues", "ci/cd",
    "machine learning", "deep learning", "data pipeline", "data pipelines",
    "service mesh", "infrastructure as code", "infrastructure-as-code",
    "github actions", "spring boot", "hugging face", "scikit learn",
})

# Inherently-lowercase technical concepts recognized without a capital.
LOWERCASE_CONCEPTS = frozenset({
    "microservices", "observability", "serverless", "containerization",
    "virtualization", "middleware", "sharding", "autoscaling", "caching",
})

# A token is a maximal run of alphanumerics plus internal tech punctuation.
_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9+.#/-]*")
_CAMEL_RE = re.compile(r"[a-z][A-Z]")
_PUNCT_TECH_RE = re.compile(r"[/+#]")
_DEGREE_CHAIN_RE = re.compile(
    r"^(?:B(?:A|S)|M(?:A|S)|PhD)(?:/(?:B(?:A|S)|M(?:A|S)|PhD))+$",
    re.I,
)


def _phrase_key(tokens: list[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(tokens)).strip().lower()


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
    if key in LOWERCASE_CONCEPTS:
        return True
    if key in KNOWN_TECH and re.search(r"[A-Z]", token):
        return True
    return _is_structural(token)


def extract_skill_phrases(jd_text: str) -> list[str]:
    """Verbatim skill phrases in first-seen order, deduped by normalized key."""
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
        # … plus the component-wise Weak semantics the gate uses: a Weak token
        # like "REST/gRPC APIs" is satisfied by a JD "REST APIs".
        return any(check._mentioned_in_jd(w, phrase) for w in weak)

    return [p for p in extract_skill_phrases(jd_text) if not _categorized(p)]


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
