from http import HTTPStatus
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from lnbits.core.crud import (
    get_installed_extensions,
    get_wallet,
)
from lnbits.core.models import User
from lnbits.decorators import check_user_exists
from lnbits.helpers import template_renderer
from lnurl import decode as lnurl_decode
from lnurl import encode as lnurl_encode
from loguru import logger

from .crud import get_fossa, get_fossa_payment
from .helpers import register_atm_payment

fossa_generic_router = APIRouter()


def fossa_renderer():
    return template_renderer(["fossa/templates"])


@fossa_generic_router.get("/", response_class=HTMLResponse)
async def index(request: Request, user: User = Depends(check_user_exists)):
    return fossa_renderer().TemplateResponse(
        "fossa/index.html",
        {"request": request, "user": user.json()},
    )


@fossa_generic_router.get("/atm", response_class=HTMLResponse)
async def atmpage(request: Request, lightning: str):

    # Debug log for the incoming lightning request
    logger.debug(lightning)

    # Decode the lightning URL
    url = str(lnurl_decode(lightning))
    if not url:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Unable to decode lnurl."
        )

    # Parse the URL to extract device ID and query parameters
    parsed_url = urlparse(url)
    device_id = parsed_url.path.split("/")[-1]
    device = await get_fossa(device_id)
    if not device:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Unable to find device."
        )

    # Extract and validate the 'p' parameter
    p = parse_qs(parsed_url.query).get("p", [None])[0]
    if p is None:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail="Missing 'p' parameter."
        )

    # Adjust for base64 padding if necessary
    p += "=" * (-len(p) % 4)

    # Decode and decrypt the 'p' parameter
    # try:
    #     # data = base64.urlsafe_b64decode(p)
    #     # decrypted = xor_decrypt(device.key.encode(), data)
    # except Exception as exc:
    #     raise HTTPException(
    #         status_code=HTTPStatus.BAD_REQUEST, detail=f"{exc!s}"
    #     ) from exc

    # Determine the price in msat
    # if device.currency != "sat":
    #     price_msat = await fiat_amount_as_satoshis(
    #        decrypted[1] / 100, device.currency)
    # else:
    #     price_msat = decrypted[1]

    # Check wallet and user access

    wallet = await get_wallet(device.wallet)
    if not wallet:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Wallet not found."
        )

    # check if boltz payouts is enabled but also check the boltz extension is enabled
    access = False
    if device.boltz:
        installed_extensions = await get_installed_extensions(active=True)
        for extension in installed_extensions:
            if extension.id == "boltz" and extension.active:
                access = True
                logger.debug(access)

    # Attempt to get recent payment information
    fossa_payment, _ = await register_atm_payment(device, p)
    assert fossa_payment, "Unable to register payment."

    # Render the response template
    return fossa_renderer().TemplateResponse(
        "fossa/atm.html",
        {
            "request": request,
            "lnurl": lightning,
            "amount": fossa_payment.sats,
            "device_id": device.id,
            "boltz": True if access else False,
            "p": p,
            "recentpay": fossa_payment.id if fossa_payment else False,
            "used": (
                True
                if fossa_payment and fossa_payment.payload == fossa_payment.payhash
                else False
            ),
        },
    )


@fossa_generic_router.get("/print/{payment_id}", response_class=HTMLResponse)
async def print_receipt(request: Request, payment_id):
    fossa_payment = await get_fossa_payment(payment_id)
    if not fossa_payment:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Payment link does not exist."
        )
    device = await get_fossa(fossa_payment.deviceid)
    if not device:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Unable to find device."
        )

    lnurl = lnurl_encode(
        str(request.url_for("fossa.lnurl_params", device_id=fossa_payment.deviceid))
        + "?atm=1&p="
        + fossa_payment.payload
    )
    logger.debug(lnurl)
    return fossa_renderer().TemplateResponse(
        "fossa/atm_receipt.html",
        {
            "request": request,
            "id": fossa_payment.id,
            "deviceid": fossa_payment.deviceid,
            "devicename": device.title,
            "payhash": fossa_payment.payhash,
            "payload": fossa_payment.payload,
            "sats": fossa_payment.sats,
            "lnurl": lnurl,
        },
    )