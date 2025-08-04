from urllib.parse import parse_qs, urlparse

from lnbits.utils.crypto import AESCipher
from lnurl import url_decode

from .models import LnurlDecrypted, LnurlPayload


def aes_decrypt_payload(payload: str, key: str) -> LnurlDecrypted:
    try:
        aes = AESCipher(key)
        decrypted = aes.decrypt(payload, urlsafe=True)
    except Exception as e:
        raise ValueError(e) from e
    pin, amount = decrypted.split(":")
    return LnurlDecrypted(pin=int(pin), amount=float(amount))


def parse_lnurl_payload(lnurl: str) -> LnurlPayload:
    try:
        url = str(url_decode(lnurl))
    except Exception as e:
        raise ValueError("Unable to decode lnurl.") from e

    # Parse the URL to extract device ID and query parameters
    parsed_url = urlparse(url)
    query_string = parse_qs(parsed_url.query)
    p = query_string.get("p", [None])[0]
    if p is None:
        raise ValueError("Missing 'p' parameter.")

    fossa_id = parsed_url.path.split("/")[-1]
    return LnurlPayload(
        fossa_id=fossa_id,
        payload=p,
    )
