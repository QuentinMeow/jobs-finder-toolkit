# Worklog — 2026-07-22-email-provider-contract

## 2026-07-22 — session 1 (claude, branch `email/stage-1-provider-contract`)

- Built the send-less mail layer at `automation/shared/mail/`:
  `contract/interface.py` (MailProvider ABC — capabilities, folder listing,
  read, review-window, opaque-token delta-sync/search stubs failing closed,
  draft ops; NO send operation, send-like subclass attributes refused),
  `contract/transport.py` (one audited stdlib-urllib transport; route policy
  asserted before network I/O; metadata-only audit log — never query strings,
  bodies, or subjects), `contract/conformance.py` (synthetic suite + read-only
  `--live` mode proving GET-only via the audit log).
- Relocated the Outlook implementation unchanged into
  `providers/outlook_graph/` (`auth.py`, `provider.py` née graph_client.py,
  `reconciliation.py`, `route_policy.py` extracted with the same routes +
  `SEND_ENDPOINT_PROBES`, `README.md` née references/graph-contract.md,
  new `synthetic.py` fixture mailbox — example.com only). Every Sent/Drafts
  duplicate-reply preflight and `isDraft: true` assertion preserved verbatim;
  the OS-keyring service string intentionally keeps the old name so cached
  logins survive.
- Replaced the fixed-file `check_draft_only.py` with the folder-walking
  `automation/shared/mail/check_mail_safety.py` (banned send patterns with the
  probe-literal exemption, SDK/HTTP-bypass/cross-provider import bans,
  route-policy probe execution, pinned scope literals, consumer CLI-surface
  pin); wired into pre-commit. Planted send-capable fixtures live inside
  `automation/shared/tests/test_mail_safety_checker.py` and the checker fails
  all of them.
- Renamed the skill `outlook-email-assistant` → `email-assistant`, no alias:
  folder, SKILL.md name/paths (tmp dir now `tmp/email-assistant/`),
  agents/openai.yaml, evals folder + canaries header, `.claude`/`.cursor`
  skill symlinks, marketplace.json, exporter PUBLIC_SKILLS, pre-commit paths,
  AGENTS.md, handbook (repo-map, public-private-split, command-cookbook),
  README.md, roadmap/current-state.md. Historical records (evals/results,
  design/token-usage-modes, memory/decisions ADR) left as records.
- Vendored the whole `mail/` tree into
  `skills/email-assistant/scripts/_vendor/mail/` (new DIR_TARGETS entry); the
  skill consumes the contract only through the vendored copy.
- Left for the owner: the one explicitly-requested read-only `--live`
  conformance run (`automation/shared/mail/contract/conformance.py
  --provider outlook_graph --live` — needs the real keyring login; never CI),
  and renaming `private/skills/references_private/outlook-email-assistant/` →
  `email-assistant` in the overlay so bootstrap_overlay relinks it.
- Eval gate: skipped — mechanical rename/relocation only; no behavioral
  instruction change (SKILL.md diffs are name, paths, and checker-command
  pointers; guardrail semantics untouched).
