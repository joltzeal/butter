"""Apple auth primitives (IDMSA / store / billing) as a library.

Only the verified implementations live here. The earlier async clients were
removed: they answered 400/541 on live traffic once the real protocol was
understood (see PROTOCOL.md), and keeping them invited silent fallbacks that
could disagree with the account's actual state.
"""

from .apple_exe_replica import IdmsaClient
from .apple_store_client import (
    StoreAuthError,
    StoreClient,
    bin_detection_str,
    detect_card_type,
    encrypt_card,
    normalize_expiry,
    random_phone,
    random_street,
)
from .apple_shld_v3 import get_jr, run_shld, solve, solve_pow, solve_sha
from .billing import (
    Address,
    encrypt_card_json,
    fill_address,
    normalize_card_expiry,
    pick_locations,
    split_expiry,
    validate_form,
)
from .cookie_scope import restore_session, snapshot_cookies
from .constants import COMMON_HEADERS, STORE_HEADERS
from .fingerprint import fd_client_info, fd_client_info_matching_common_headers
from .hashcash import solve_challenge
from .http import Transport, mask_proxy, new_fetch_id, resolve_host, rotate_sid
from .protocol_login import ProtocolLoginError, protocol_login
from .session import SavedSession, SessionManager

__all__ = [
    "Address",
    "COMMON_HEADERS",
    "IdmsaClient",
    "ProtocolLoginError",
    "STORE_HEADERS",
    "SavedSession",
    "SessionManager",
    "StoreAuthError",
    "StoreClient",
    "Transport",
    "bin_detection_str",
    "detect_card_type",
    "encrypt_card",
    "encrypt_card_json",
    "fd_client_info",
    "fd_client_info_matching_common_headers",
    "fill_address",
    "mask_proxy",
    "new_fetch_id",
    "normalize_card_expiry",
    "normalize_expiry",
    "pick_locations",
    "protocol_login",
    "random_phone",
    "random_street",
    "resolve_host",
    "restore_session",
    "rotate_sid",
    "run_shld",
    "snapshot_cookies",
    "solve_challenge",
    "get_jr",
    "solve",
    "solve_pow",
    "solve_sha",
    "split_expiry",
    "validate_form",
]
