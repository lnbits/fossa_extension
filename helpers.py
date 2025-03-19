from base64 import b64decode
from urllib.parse import parse_qs, urlparse

from Cryptodome.Cipher import AES
from lnurl import decode as lnurl_decode
from pydantic import BaseModel


class LnurlPayload(BaseModel):
    fossa_id: str
    iv: str
    payload: str


class LnurlDecrypted(BaseModel):
    pin: int
    amount: float


def parse_lnurl_payload(lnurl: str) -> LnurlPayload:

    # Decode the lightning URL
    try:
        url = str(lnurl_decode(lnurl))
    except Exception as e:
        raise ValueError("Unable to decode lnurl.") from e

    # Parse the URL to extract device ID and query parameters
    parsed_url = urlparse(url)
    query_string = parse_qs(parsed_url.query)

    p = query_string.get("p", [None])[0]
    if p is None:
        raise ValueError("Missing 'p' parameter.")

    # Extract and validate the 'iv' parameter
    iv = query_string.get("iv", [None])[0]
    if iv is None:
        raise ValueError("Missing 'iv' parameter.")

    fossa_id = parsed_url.path.split("/")[-1]

    return LnurlPayload(
        fossa_id=fossa_id,
        iv=iv,
        payload=p,
    )


def decrypt_payload(key, iv, payload) -> LnurlDecrypted:
    _iv = b64decode(iv)
    _ct = b64decode(payload)
    if len(_ct) % 16 != 0:
        raise ValueError("Invalid payload length.")
    if len(_iv) != 32:
        raise ValueError("Invalid IV length.")
    cipher = AES.new(key.encode(), AES.MODE_CBC, _iv)
    pt = cipher.decrypt(_ct)
    msg = pt.split(b"\x00")[0].decode()
    pin, amount = msg.split(":")
    if 1000 > int(pin) > 9999:
        raise ValueError("Invalid pin")
    if float(amount) < 0:
        raise ValueError("Invalid amount")
    return LnurlDecrypted(pin=int(pin), amount=float(amount))
