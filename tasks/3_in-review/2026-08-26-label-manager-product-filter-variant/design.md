# Design — label the manager-product filter variant

## Decision

Add one fictional corpus row for the existing manager-product review family, one corpus boundary
for a non-delimited `Manager Tools` title, and one snapshot-audit test that reproduces issue #234.
Reuse the existing true-manager corpus and unit-test controls.

## Rejected alternatives

- Changing the classifier would alter production behavior when only its audit vocabulary is stale.
- Whitelisting the reported hash would hide meaning and could mask a future semantic collision.
- Exempting every title that contains `Manager` would leak real management roles through the gate.

## Consequences and rollback

Runtime title decisions do not change. The audit learns one supported review signature, while the
canonical title assessor keeps the true-manager and non-delimited-tool fixtures at `no_match` under
their explicit include/exclude profile. That is not a universal pipeline hard exclusion: configured
`titles.word_filter.include` or `soft_exclude` rules run at the pipeline boundary and may
intentionally rescue an assessor `no_match` to review. Revert the new corpus rows and audit test if
an assessor verdict changes under the fixture profile or either fixture maps to an unintended
signature.
