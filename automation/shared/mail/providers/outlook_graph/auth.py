"""Microsoft device-code OAuth with refresh state stored only in the OS keyring."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import UUID

DELEGATED_SCOPES = (
    "https://graph.microsoft.com/User.Read",
    "https://graph.microsoft.com/Mail.ReadWrite",
)
OAUTH_SCOPES = ("openid", "profile", "offline_access", *DELEGATED_SCOPES)
# Stable OS-keyring credential key. Predates the skill's rename to
# email-assistant; changing it would orphan every user's cached login.
KEYRING_SERVICE = "jobs-finder-combined.outlook-email-assistant.oauth"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"


class AuthError(RuntimeError):
    """Authentication or secure-token-storage failure."""


class LoginRequired(AuthError):
    """No usable cached refresh token is available."""


@dataclass(frozen=True)
class OutlookSettings:
    account: str
    client_id: str
    tenant: str = "consumers"

    def validate(self) -> None:
        if not self.account or "@" not in self.account:
            raise AuthError("outlook_email.account must be set to the expected mailbox")
        try:
            UUID(self.client_id)
        except (ValueError, AttributeError) as exc:
            raise AuthError("outlook_email.client_id must be a Microsoft application UUID") from exc
        if self.tenant != "consumers":
            raise AuthError("outlook_email.tenant must be 'consumers' for personal Outlook")

    @property
    def authority(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant}"

    @property
    def device_endpoint(self) -> str:
        return f"{self.authority}/oauth2/v2.0/devicecode"

    @property
    def token_endpoint(self) -> str:
        return f"{self.authority}/oauth2/v2.0/token"

    @property
    def cache_key(self) -> str:
        return self.account.casefold()


def _keyring():
    try:
        import keyring  # type: ignore
    except ImportError as exc:
        raise AuthError(
            "missing OS-keyring dependency; run .venv/bin/pip install -r requirements.txt"
        ) from exc
    return keyring


def dependency_status() -> dict[str, str]:
    try:
        module = __import__("keyring")
        return {"keyring": str(getattr(module, "__version__", "installed"))}
    except ImportError:
        return {"keyring": "missing"}


def _post_form(url: str, values: dict[str, str]) -> dict[str, Any]:
    request = Request(
        url,
        data=urlencode(values).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read()
    except HTTPError as exc:
        raw = exc.read()
        try:
            return json.loads(raw)
        except json.JSONDecodeError as decode_exc:
            raise AuthError(f"Microsoft OAuth returned HTTP {exc.code}") from decode_exc
    except URLError as exc:
        raise AuthError(f"Microsoft OAuth connection failed: {exc.reason}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AuthError("Microsoft OAuth returned invalid JSON") from exc


class AuthManager:
    def __init__(self, settings: OutlookSettings):
        settings.validate()
        self.settings = settings

    @staticmethod
    def _scope_value() -> str:
        return " ".join(OAUTH_SCOPES)

    def _load_refresh_token(self) -> str:
        keyring = _keyring()
        try:
            serialized = keyring.get_password(KEYRING_SERVICE, self.settings.cache_key)
        except Exception as exc:
            raise AuthError(f"OS keyring is unavailable: {exc}") from exc
        if not serialized:
            raise LoginRequired("no cached login; run the login command")
        try:
            state = json.loads(serialized)
        except json.JSONDecodeError as exc:
            raise LoginRequired("OAuth cache is invalid; run logout, then login") from exc
        if state.get("client_id") != self.settings.client_id:
            raise LoginRequired("OAuth cache belongs to another app registration; run login")
        token = str(state.get("refresh_token") or "")
        if not token:
            raise LoginRequired("OAuth cache has no refresh token; run login")
        return token

    def _save_refresh_token(self, token: str) -> None:
        if not token:
            raise AuthError("Microsoft did not return an OAuth refresh token")
        state = json.dumps(
            {
                "account": self.settings.account,
                "client_id": self.settings.client_id,
                "refresh_token": token,
                "tenant": self.settings.tenant,
            },
            separators=(",", ":"),
        )
        keyring = _keyring()
        try:
            keyring.set_password(KEYRING_SERVICE, self.settings.cache_key, state)
        except Exception as exc:
            raise AuthError(f"could not save OAuth state in the OS keyring: {exc}") from exc

    @staticmethod
    def _raise_result_error(result: dict[str, Any]) -> None:
        description = result.get("error_description") or result.get("error") or "unknown error"
        raise AuthError(f"Microsoft authentication failed: {description}")

    def access_token(self) -> str:
        refresh_token = self._load_refresh_token()
        result = _post_form(
            self.settings.token_endpoint,
            {
                "client_id": self.settings.client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": self._scope_value(),
            },
        )
        if "access_token" not in result:
            error = str(result.get("error") or "")
            if error in {"invalid_grant", "interaction_required"}:
                raise LoginRequired("cached login expired or was revoked; run login")
            self._raise_result_error(result)
        self._save_refresh_token(str(result.get("refresh_token") or refresh_token))
        return str(result["access_token"])

    def login(self, printer: Callable[[str], None] = print) -> str:
        flow = _post_form(
            self.settings.device_endpoint,
            {"client_id": self.settings.client_id, "scope": self._scope_value()},
        )
        if "device_code" not in flow:
            self._raise_result_error(flow)
        printer(str(flow.get("message") or "Follow Microsoft's device-login instructions."))
        interval = max(1, int(flow.get("interval") or 5))
        deadline = time.monotonic() + max(60, int(flow.get("expires_in") or 900))
        while time.monotonic() < deadline:
            time.sleep(interval)
            result = _post_form(
                self.settings.token_endpoint,
                {
                    "client_id": self.settings.client_id,
                    "device_code": str(flow["device_code"]),
                    "grant_type": DEVICE_GRANT,
                },
            )
            if "access_token" in result:
                self._save_refresh_token(str(result.get("refresh_token") or ""))
                return str(result["access_token"])
            error = str(result.get("error") or "")
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                interval += 5
                continue
            self._raise_result_error(result)
        raise AuthError("Microsoft device login expired; run login again")

    def logout(self) -> bool:
        keyring = _keyring()
        try:
            existing = keyring.get_password(KEYRING_SERVICE, self.settings.cache_key)
            if existing is None:
                return False
            keyring.delete_password(KEYRING_SERVICE, self.settings.cache_key)
            return True
        except Exception as exc:
            raise AuthError(f"could not clear OAuth state from the OS keyring: {exc}") from exc
