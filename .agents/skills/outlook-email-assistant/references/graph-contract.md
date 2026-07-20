# Microsoft Graph draft-only contract

Read this reference when configuring OAuth, changing Graph code, or debugging permissions.

## Public/private boundary

Public and tracked:

- `SKILL.md`, Graph/OAuth scripts, tests, canaries, and the empty example configuration.
- Generic drafting rules and safety checks.

Private and never tracked in the public toolkit:

- `outlook_email.account` and `outlook_email.client_id` in git-ignored `config.yaml`.
- OAuth refresh-token state in the operating-system keyring.
- Mailbox content, suggested reply bodies, and any personal writing preferences.

Mailbox content is streamed to the active agent and is not cached by these scripts. Disposable
body files belong under `tmp/outlook-email-assistant/` and are removed after draft creation.

## Authentication contract

- Authority: `https://login.microsoftonline.com/consumers`.
- App type: native/mobile public client; no client secret.
- Flow: Microsoft identity-platform device-code flow for initial consent, refresh-token grant
  afterward. The implementation uses the documented OAuth endpoints directly to avoid native
  cryptography build dependencies in the repo's portable Python environment.
- Delegated scopes: exactly `User.Read` and `Mail.ReadWrite`.
- Expected mailbox: required in private config and compared case-insensitively with the signed-in
  Microsoft identity and `/me` response.
- Token storage: OS keyring only. Fail closed when no functional keyring is available.

`Mail.ReadWrite` is necessary because Microsoft Graph creates drafts in the Drafts folder. Do not
grant `Mail.Send`. The runtime additionally narrows the broad mailbox permission with a fixed route
allowlist and no arbitrary-request interface.

## Allowed Graph surface

The client permits only these operations beneath `https://graph.microsoft.com/v1.0`:

| Method | Route shape | Purpose |
|---|---|---|
| `GET` | `/me` | Verify the signed-in mailbox |
| `GET` | `/me/mailFolders/inbox/messages` | List recent inbox messages |
| `GET` | `/me/mailFolders/sentitems/messages` | Reconcile whether an inbound message was answered |
| `GET` | `/me/mailFolders/drafts/messages` | List existing drafts |
| `GET` | `/me/messages/{id}` | Read one message or verify one draft |
| `POST` | `/me/messages` | Create a new draft |
| `POST` | `/me/messages/{id}/createReply` | Create a reply draft |
| `PATCH` | `/me/messages/{id}` | Update a confirmed draft body |

Every other route/method is rejected before network I/O. Draft-creating/updating operations assert
`isDraft is True` on Graph's response. The reply workflow verifies the initial reply draft, patches
it, then fetches and verifies it again. Before any reply-draft write, the client reads the source
message and compares its conversation against recent Sent Items and Drafts. It refuses to create a
reply draft when a later Sent reply or an existing conversation draft is found.

## Defense in depth

1. Repo instructions prohibit sending.
2. OAuth lacks `Mail.Send`.
3. Runtime routes are allowlisted; callers cannot provide raw URLs.
4. Sent/Drafts reconciliation blocks avoidable duplicate replies before a mailbox write.
5. CLI contains no send operation.
6. Runtime refuses writes not confirmed as drafts.
7. `check_draft_only.py` scans executable source and the CLI/API shape.
8. Unit tests exercise Sent reconciliation, duplicate-draft prevention, rejected send-like routes,
   and false `isDraft` responses.
9. The tracked pre-commit hook runs the static checker.

Changing any one layer does not silently introduce sending. Adding a send path requires an explicit
multi-file harness change that should be rejected because the user's permanent policy is manual send.
