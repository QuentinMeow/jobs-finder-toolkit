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
true-manager and non-delimited-tool boundaries stay hard exclusions. Revert the new corpus rows and
audit test if a production verdict changes or either fixture maps to an unintended signature.
