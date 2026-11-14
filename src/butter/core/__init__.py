"""Domain layer: storage, proxy plane, clipboard parsing, orchestration."""

from .address_parser import parse_clipboard
from .proxy import ProxyController, ProxyStatus, build_profile, render_profile
from .services import BillingForm, LoginRequest, Services
from .store import Account, AccountStore, Settings, atomic_write, data_dir

__all__ = [
    "Account",
    "AccountStore",
    "BillingForm",
    "LoginRequest",
    "ProxyController",
    "ProxyStatus",
    "Services",
    "Settings",
    "atomic_write",
    "build_profile",
    "data_dir",
    "parse_clipboard",
    "render_profile",
]
