# Worklog — 2026-07-22-registry-match-keys-exact-lookup-misses-name-variants

## 2026-07-22 — session 1 (Cursor agent)

- Added conservative, namespaced legal-suffix comparison keys with ambiguous-base
  abstention in the registry.
- Routed applications-log company/role pairs through the same registry key sets
  already used by the blacklist and company-search log.
- Added fictional registry and end-to-end skip-log regressions.

## 2026-07-22 — session 2 (GPT-5.6 Sol)

- Rebased the uncommitted work onto the latest `main` after the AgentFold
  restructure moved `.agents/skills` to `skills` and `scripts` to `automation`.
- Preserved schema-v5 upstream changes while migrating all tracked edits and the
  previously untracked skip-identity test to their canonical paths.
- Refreshed the venv with the newly declared `zstandard` dependency and verified
  the complete affected suites.
