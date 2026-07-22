"""Isolated mail-provider implementations — one folder per provider.

Rules (design/raw-data-layer/03-provider-interfaces.md, isolation rules):
no shared files between provider folders, no cross-imports, no provider SDKs,
all network I/O through the contract's audited transport. Enforced by
``automation/shared/mail/check_mail_safety.py``, which walks every folder here.
"""
