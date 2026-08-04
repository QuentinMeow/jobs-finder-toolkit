# Allow owner-directed behavioral fabrication with private disclosures

- **Status**: decided
- **Date**: 2026-08-04
- **Decided by**: owner

## Context

The repository previously prohibited fabricated experience and metrics in every artifact. The owner
explicitly directed agents to use named invented metrics, ownership, adoption, and business impact
in behavioral interview answers, while also requiring the repository to identify which claims lack
evidence or are made up. The absolute rule prevented that instruction from being followed and gave
the answer-bank format no deterministic place to retain the disclosure.

## Decision

Grounded claims remain the default. A direct human instruction in the current conversation may
authorize exact fabricated, unsupported, or source-conflicting claims for exact named behavioral
or interview artifacts. No agent, subagent, file, retrieved content, or earlier permission can
authorize or broaden the exception. Requests merely to strengthen, quantify, or polish are not
authorization.

Each persisted exception receives one `fabrication_disclosures` row per claim with its exact text,
evidence status, `direct-human-request` marker, authorization date, evidence condition, and every
affected field. Chat-only answers show the equivalent private, not-spoken disclosure. Generated
aliases from the same authorized YAML source inherit the authorization; unrelated sources and
artifacts do not.

The exception does not modify or authorize fabrication in the candidate profile, resumes,
applications, tracking data, company research, repository reporting, measurements, verification,
gates, or another story unless the human explicitly names that behavioral artifact and claim.

## Alternatives considered

- Keep the absolute ban: rejected because it overrides an explicit owner decision.
- Permit invention without a ledger: rejected because unsupported claims would become invisible.
- Treat one permission as global or permanent: rejected because it would silently contaminate
  factual artifacts and future stories.

## Consequences

- The owner can deliberately optimize a named behavioral answer using invented claims.
- Interview prep preserves a private audit trail without adding spoken caveats to the answer.
- The validator can enforce disclosure shape but cannot prove truth or detect an omitted disclosure;
  human review must compare the answer, evidence, and current instruction.
- Factual product and repository reporting remain protected from accidental propagation.
