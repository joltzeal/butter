"""Card + address material: RSA-OAEP encryption, card typing, random fill.

Straight port of the reference ``save_billing`` helpers:

* ``encrypt_card``  — RSA-OAEP(SHA-256) over the card number, returned as the
  ``{"cipherText","publicKeyHash"}`` JSON that ``saveBillingDetails`` expects.
* ``detect_card_type`` / ``bin_detection_str`` — card brand + BIN prefix.
* ``pick_locations`` / ``random_*`` — fill gaps with plausible regional data
  when the operator leaves the address blank.
"""

from __future__ import annotations

import base64
import json
import random
import re
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


def encrypt_card(card_number: str, pub_key_b64: str, key_hash: str) -> dict[str, str]:
    key_der = base64.b64decode(pub_key_b64)
    public_key = serialization.load_der_public_key(key_der)
    cipher = public_key.encrypt(
        card_number.encode(),
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=b""),
    )
    return {
        "cipherText": base64.b64encode(cipher).decode(),
        "publicKeyHash": key_hash,
    }


def encrypt_card_json(card_number: str, pub_key_b64: str, key_hash: str) -> str:
    return json.dumps(encrypt_card(card_number, pub_key_b64, key_hash), separators=(",", ":"))


def detect_card_type(card_number: str) -> str:
    digits = re.sub(r"\D", "", card_number or "")
    if digits.startswith("4"):
        return "VISA"
    if digits[:2] in ("34", "37"):
        return "AMERICAN_EXPRESS"
    if digits.startswith("6"):
        return "DISCOVER"
    if digits.startswith("5"):
        return "MASTERCARD"
    return "VISA"


def bin_detection_str(card_number: str) -> str:
    return re.sub(r"\D", "", card_number or "")[:6]


def normalize_card_expiry(value: str) -> str:
    """Return ``MM/YY`` for the accepted shapes ``M/YY``, ``MM/YYYY``, ``MM-YY``."""
    raw = (value or "").strip()
    m = re.fullmatch(r"(\d{1,2})\s*/\s*(\d{2,4})", raw)
    if m:
        month, year = m.group(1), m.group(2)
    else:
        cleaned = re.sub(r"\D+", "", raw)
        if len(cleaned) == 6:  # YYYYMM
            month, year = cleaned[4:], cleaned[2:4]
        elif len(cleaned) in (3, 4):
            month, year = cleaned[:-2], cleaned[-2:]
        else:
            return raw
    month = month.zfill(2)
    if len(year) == 4:
        year = year[2:]
    return f"{month}/{year}"


def split_expiry(value: str) -> tuple[str, str]:
    normalized = normalize_card_expiry(value)
    if "/" in normalized:
        month, year = normalized.split("/", 1)
        if len(year) == 4:
            year = year[2:]
        return month, year
    return "01", "30"


# --- regional filler data --------------------------------------------------
US_LOCATIONS: dict[str, list[tuple[str, str]]] = {
    "CA": [("San Jose", "95112"), ("Los Angeles", "90012"), ("San Diego", "92101")],
    "NY": [("New York", "10001"), ("Brooklyn", "11201"), ("Buffalo", "14202")],
    "TX": [("Austin", "78701"), ("Houston", "77002"), ("Dallas", "75201")],
    "FL": [("Miami", "33101"), ("Orlando", "32801"), ("Tampa", "33602")],
    "IL": [("Chicago", "60601"), ("Naperville", "60540")],
    "WA": [("Seattle", "98101"), ("Spokane", "99201")],
    "MA": [("Boston", "02108"), ("Cambridge", "02139")],
    "NJ": [("Newark", "07102"), ("Jersey City", "07302")],
}

GB_LOCATIONS = [
    ("Greater London", "SW1A 1AA", "London"),
    ("Greater Manchester", "M1 1AE", "Manchester"),
    ("West Midlands", "B1 1AA", "Birmingham"),
    ("West Yorkshire", "LS1 1UR", "Leeds"),
    ("Merseyside", "L1 8JQ", "Liverpool"),
    ("South Yorkshire", "S1 2HE", "Sheffield"),
    ("Bristol", "BS1 4DJ", "Bristol"),
    ("Edinburgh", "EH1 1YZ", "Edinburgh"),
    ("Cardiff", "CF10 1EP", "Cardiff"),
    ("Belfast", "BT1 1AA", "Belfast"),
]

AU_LOCATIONS = [
    ("NSW", "2000", "Sydney"),
    ("VIC", "3000", "Melbourne"),
    ("QLD", "4000", "Brisbane"),
    ("SA", "5000", "Adelaide"),
    ("WA", "6000", "Perth"),
    ("TAS", "7000", "Hobart"),
    ("NT", "0800", "Darwin"),
    ("ACT", "2600", "Canberra"),
]

CA_LOCATIONS = [
    ("ON", "M5V 2T6", "Toronto"),
    ("BC", "V6B 1A1", "Vancouver"),
    ("QC", "H2Y 1C6", "Montreal"),
    ("AB", "T2P 2M5", "Calgary"),
]

FIRST_NAMES = [
    "James",
    "John",
    "Robert",
    "Michael",
    "William",
    "David",
    "Richard",
    "Joseph",
    "Thomas",
    "Charles",
    "Mary",
    "Patricia",
    "Jennifer",
    "Linda",
    "Barbara",
    "Elizabeth",
    "Susan",
    "Jessica",
    "Sarah",
]
LAST_NAMES = [
    "Smith",
    "Johnson",
    "Williams",
    "Brown",
    "Jones",
    "Garcia",
    "Miller",
    "Davis",
    "Wilson",
    "Anderson",
    "Taylor",
    "Thomas",
    "Jackson",
    "White",
]

_STREETS = [
    "Maple Ave",
    "Oak St",
    "Pine St",
    "Elm Ave",
    "River Rd",
    "Lake View Dr",
    "Washington St",
    "Park Blvd",
    "Cedar Ln",
    "Sunset Blvd",
]

_EN_COUNTRY = {"US": "US", "GB": "GB", "AU": "AU", "CA": "CA"}


@dataclass
class Address:
    first_name: str
    last_name: str
    street: str
    street2: str
    city: str
    state: str
    postal_code: str
    country_code: str
    phone: str

    def as_dict(self) -> dict[str, str]:
        return {
            "first_name": self.first_name,
            "last_name": self.last_name,
            "street": self.street,
            "street2": self.street2,
            "city": self.city,
            "state": self.state,
            "postal_code": self.postal_code,
            "country_code": self.country_code,
            "phone": self.phone,
        }


def random_street(rng: random.Random | None = None) -> str:
    rng = rng or random
    return f"{rng.randint(100, 9999)} {rng.choice(_STREETS)}"


def random_phone(country: str = "US", rng: random.Random | None = None) -> str:
    rng = rng or random
    country = country.upper()
    if country == "GB":
        return f"07{rng.randint(100, 999)} {rng.randint(100000, 999999)}"
    if country == "AU":
        return f"04{rng.randint(10, 99)} {rng.randint(100000, 999999)}"
    if country == "CA":
        return f"{rng.randint(200, 999)}{rng.randint(200, 999)}{rng.randint(1000, 9999)}"
    area = rng.choice(["212", "305", "415", "512", "617", "702", "206"])
    return f"{area}{rng.randint(200, 999)}{rng.randint(1000, 9999)}"


def pick_locations(country: str, rng: random.Random | None = None) -> tuple[str, str, str]:
    rng = rng or random
    country = country.upper()
    if country == "GB":
        state, postal, city = rng.choice(GB_LOCATIONS)
        return state, postal, city
    if country == "AU":
        state, postal, city = rng.choice(AU_LOCATIONS)
        return state, postal, city
    if country == "CA":
        state, postal, city = rng.choice(CA_LOCATIONS)
        return state, postal, city
    state = rng.choice(list(US_LOCATIONS))
    city, postal = rng.choice(US_LOCATIONS[state])
    return state, postal, city


def fill_address(form: dict, rng: random.Random | None = None) -> Address:
    rng = rng or random
    country = (form.get("country_code") or "US").upper()
    state, postal, city = pick_locations(country, rng)
    return Address(
        first_name=form.get("first_name") or rng.choice(FIRST_NAMES),
        last_name=form.get("last_name") or rng.choice(LAST_NAMES),
        street=form.get("street") or random_street(rng),
        street2=form.get("street2") or "",
        city=form.get("city") or city,
        state=form.get("state") or state,
        postal_code=form.get("postal_code") or postal,
        country_code=country,
        phone=form.get("phone") or random_phone(country, rng),
    )


def validate_form(form: dict) -> list[str]:
    missing = []
    if not re.sub(r"\D", "", form.get("card_number") or ""):
        missing.append("card_number")
    if not (form.get("card_expiry") or "").strip():
        missing.append("card_expiry")
    return missing
