"""Persistent configuration + account storage.

Layout (all under the user data dir, ``~/Library/Application Support/butter`` on
macOS, ``%APPDATA%\\butter`` on Windows, ``~/.local/share/butter`` on Linux):

    settings.json   proxy / line / UI preferences
    accounts.json   account records (cookies + fingerprint + note)

Writes are atomic (temp file + ``os.replace``) so a crash cannot truncate the
account database.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def data_dir() -> Path:
    override = os.environ.get("BUTTER_DATA_DIR")
    if override:
        path = Path(override).expanduser()
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / "butter"
    elif os.name == "nt":
        path = Path(os.environ.get("APPDATA", Path.home())) / "butter"
    else:
        path = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "butter"
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, suffix=".tmp", delete=False, encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        tmp = Path(handle.name)
    os.replace(tmp, path)


@dataclass
class Settings:
    proxy_mode: str = "direct"  # direct | custom | clash | mihomo
    proxy_url: str = ""  # direct mode override
    proxy_host: str = ""  # mihomo dialer host
    proxy_port: int = 0
    proxy_user: str = ""
    proxy_pass: str = ""
    proxy_type: str = "socks5"
    hk_nodes: list[dict[str, Any]] = field(default_factory=list)
    # Control an already-running mihomo/Clash core over its REST API.
    clash_api: str = ""  # e.g. 127.0.0.1:9090
    clash_secret: str = ""
    clash_group: str = ""  # selector group to switch, e.g. 节点选择
    clash_socks: str = ""  # that core's socks/mixed inbound, e.g. socks5h://127.0.0.1:7891
    line: str = "HK"  # HK | US
    impersonate: str = "chrome142"
    timezone: str = "Asia/Shanghai"
    session_auto_check: bool = False
    session_check_top: int = 5
    # Background keep-alive: re-checks (and renews) the store session of online
    # accounts on an interval so a billing read never has to handshake first.
    # Light liveness poll: only checks whether the session still answers, and
    # flips the account to offline when it does not. Cheap, so it runs often.
    session_poll: bool = True
    session_poll_seconds: int = 20
    retry_attempts: int = 3
    verbose_network_log: bool = False
    # Byte-exact X-Apple-I-FD-Client-Info from a real browser (paste once).
    fd_client_info: str = ""

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        target = path or (data_dir() / "settings.json")
        if not target.exists():
            return cls()
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self, path: Path | None = None) -> None:
        target = path or (data_dir() / "settings.json")
        atomic_write(target, json.dumps(asdict(self), ensure_ascii=False, indent=2))

    def proxy_url_for(self, sid: str = "", region: str = "") -> str | None:
        """Resolve the proxy string handed to the HTTP transport."""
        if self.proxy_mode == "direct":
            return self.proxy_url or None
        if self.proxy_mode == "clash":
            # Reuse the user's existing core; node choice happens via its API.
            return self.clash_socks or None
        if self.proxy_mode == "mihomo":
            return "socks5h://127.0.0.1:7890"  # mihomo mixed port managed below
        # A plain URL wins over the host/port fields: that is what "custom"
        # means, and ignoring it silently fell back to a direct connection.
        if self.proxy_url:
            return self.proxy_url
        if not self.proxy_host:
            return None
        user = self.proxy_user
        if region:
            user = f"{user}-region-{region}"
        if sid:
            user = f"{user}-sid-{sid}-t-10"
        cred = user if not self.proxy_pass else f"{user}:{self.proxy_pass}"
        return f"{self.proxy_type}://{cred}@{self.proxy_host}:{self.proxy_port}"


@dataclass
class Account:
    email: str
    password: str = ""
    note: str = ""
    cookies: dict[str, str] = field(default_factory=dict)
    fingerprint: dict[str, Any] = field(default_factory=dict)
    stk: str = ""
    logged_in: bool = False
    last_login: str = ""
    status: str = "idle"  # idle | checking | online | offline
    # Insertion stamp; the list reads oldest-first so new rows land at the end.
    created_at: str = ""
    billing_checked: bool = False
    has_card: bool = False
    card_suffix: str = ""
    billing_updated_at: str = ""
    # Last successfully read billing payload, so the UI can paint instantly and
    # only refresh in the background.
    # Last store host that actually answered; skips the warmup walk next time.
    store_base: str = ""

    @property
    def has_des(self) -> bool:
        return any(key.startswith("DES") for key in self.cookies)

    def public(self) -> dict[str, Any]:
        data = asdict(self)
        data["password"] = "***" if self.password else ""
        data["password_plain"] = self.password
        data["has_password"] = bool(self.password)
        data["has_des"] = self.has_des
        return data


class AccountStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (data_dir() / "accounts.json")
        self._accounts: list[Account] = []
        self.load()

    def load(self) -> list[Account]:
        if not self.path.exists():
            self._accounts = []
            return self._accounts
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = []
        known = set(Account.__dataclass_fields__)
        accounts = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            accounts.append(Account(**{k: v for k, v in item.items() if k in known}))
        self._accounts = accounts
        return accounts

    def save(self) -> None:
        payload = json.dumps([asdict(a) for a in self._accounts], ensure_ascii=False, indent=2)
        atomic_write(self.path, payload)

    @property
    def accounts(self) -> list[Account]:
        # Oldest first: a freshly added account belongs at the bottom of the
        # table, not wherever it happened to be appended.
        return sorted(self._accounts, key=lambda a: a.created_at or "")

    def get(self, email: str) -> Account | None:
        return next((a for a in self._accounts if a.email.lower() == email.lower()), None)

    def upsert(self, account: Account) -> Account:
        existing = self.get(account.email)
        if existing:
            for field_name in Account.__dataclass_fields__:
                setattr(existing, field_name, getattr(account, field_name))
            self.save()
            return existing
        self._accounts.append(account)
        self.save()
        return account

    def remove(self, email: str) -> bool:
        before = len(self._accounts)
        self._accounts = [a for a in self._accounts if a.email.lower() != email.lower()]
        if len(self._accounts) != before:
            self.save()
            return True
        return False

    def reorder(self, emails: list[str]) -> None:
        order = {email.lower(): index for index, email in enumerate(emails)}
        self._accounts.sort(key=lambda a: order.get(a.email.lower(), len(order)))
        self.save()
