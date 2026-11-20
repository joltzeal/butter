"""Typed request/response models for the HTTP API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AccountIn(BaseModel):
    email: str
    password: str = ""
    note: str = ""


class AccountUpdate(BaseModel):
    password: str | None = None
    note: str | None = None
    # Renaming the key: sessions and billing cache belong to the old address.
    email: str | None = None


class AccountOut(BaseModel):
    email: str
    note: str = ""
    status: str = "idle"
    logged_in: bool = False
    last_login: str = ""
    has_password: bool = False
    # The stored password, in the clear: the UI shows and edits it in place.
    password_plain: str = ""
    has_des: bool = False
    billing_checked: bool = False
    has_card: bool = False
    card_suffix: str = ""
    billing_updated_at: str = ""
    code_url: str = ""
    # True while the login is parked waiting for a 2FA code.
    awaiting_hsa2: bool = False


class LoginIn(BaseModel):
    email: str
    password: str = ""
    note: str = ""
    persist: bool = True
    # 2FA hooks for the verified chain: a literal code, or a URL serving it.
    code: str = ""
    code_url: str = ""
    force_legacy: bool = False


class BulkIn(BaseModel):
    text: str = ""


class BulkLineError(BaseModel):
    line: int
    text: str
    reason: str


class BulkOut(BaseModel):
    ok: bool
    message: str = ""
    created: int = 0
    updated: int = 0
    accounts: list[str] = []
    errors: list[BulkLineError] = []


class BillingFormIn(BaseModel):
    card_number: str = ""
    card_expiry: str = ""
    first_name: str = ""
    last_name: str = ""
    street: str = ""
    street2: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    country_code: str = "US"
    phone: str = ""
    remove_only: bool = False


class Hsa2In(BaseModel):
    code: str


class SettingsIn(BaseModel):
    proxy_mode: Literal["direct", "custom", "clash", "mihomo"] | None = None
    proxy_url: str | None = None
    proxy_host: str | None = None
    proxy_port: int | None = None
    proxy_user: str | None = None
    proxy_pass: str | None = None
    proxy_type: str | None = None
    line: Literal["HK", "US"] | None = None
    impersonate: str | None = None
    timezone: str | None = None
    session_auto_check: bool | None = None
    session_check_top: int | None = None
    session_poll: bool | None = None
    session_poll_seconds: int | None = None
    retry_attempts: int | None = None
    verbose_network_log: bool | None = None
    fd_client_info: str | None = None
    hk_nodes: list[dict[str, Any]] | None = None
    clash_api: str | None = None
    clash_secret: str | None = None
    clash_group: str | None = None
    clash_socks: str | None = None


class PasteIn(BaseModel):
    text: str = Field("", description="Clipboard payload to parse")


class ClashSelectIn(BaseModel):
    group: str = ""
    node: str


class ClashRotateIn(BaseModel):
    group: str = ""
    keyword: str = ""
    stride: int = 1


class ReorderIn(BaseModel):
    emails: list[str]


class CheckIn(BaseModel):
    emails: list[str] | None = None


class ParseOut(BaseModel):
    fields: dict[str, str]
    count: int
