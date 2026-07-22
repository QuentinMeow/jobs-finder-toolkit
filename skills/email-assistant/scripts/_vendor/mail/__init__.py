"""Send-less mail layer: one provider contract, isolated provider folders.

Design: ``design/raw-data-layer/03-provider-interfaces.md``. Safety lives here,
once — below every consumer skill: the contract has NO send operation, every
provider routes network I/O through the audited transport with a per-provider
route allowlist, and ``check_mail_safety.py`` walks every provider folder.
"""
