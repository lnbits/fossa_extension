from http import HTTPStatus
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from lnbits.core.crud import (
    get_installed_extensions,
    get_wallet,
)
from lnbits.core.models import User
from lnbits.decorators import check_user_exists
from lnbits.helpers import template_renderer
from lnbits.utils.exchange_rates import fiat_amount_as_satoshis
from loguru import logger

from .crud import get_fossa, get_fossa_payment
from .helpers import aes_decrypt_payload, parse_lnurl_payload

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

    lnurl_payload = parse_lnurl_payload(lightning)
    fossa = await get_fossa(lnurl_payload.fossa_id)
    if not fossa:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Unable to find fossa."
        )
    # Check wallet and user access
    wallet = await get_wallet(fossa.wallet)
    if not wallet:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Wallet not found."
        )

    # check if boltz payouts is enabled but also check the boltz extension is enabled
    if fossa.boltz:
        installed_extensions = await get_installed_extensions(active=True)
        for extension in installed_extensions:
            if extension.id == "boltz" and extension.active:
                fossa.boltz = False

    # decrypt the payload to get the amount
    try:
        decrypted = aes_decrypt_payload(lnurl_payload.payload, fossa.key)
    except Exception as e:
        logger.debug(f"Error decrypting payload: {e}")
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Invalid payload.."
        ) from e
    price_sat = (
        await fiat_amount_as_satoshis(decrypted.amount / 100, fossa.currency)
        if fossa.currency != "sat"
        else ceil(float(decrypted.amount))
    )
    if price_sat is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Price fetch error."
        )

    price_sat = int(price_sat * ((fossa.profit / 100) + 1))

    # get to determine if the payload has been used
    payment = await get_fossa_payment(lnurl_payload.payload)

    return fossa_renderer().TemplateResponse(
        "fossa/atm.html",
        {
            "request": request,
            "lnurl": lightning,
            "amount_sat": price_sat,
            "fossa_id": fossa.id,
            "boltz": fossa.boltz,
            "used": payment and payment.payment_hash,
        },
    )


@fossa_generic_router.get("/print/{payment_id}", response_class=HTMLResponse)
async def print_receipt(request: Request, payment_id):
    fossa_payment = await get_fossa_payment(payment_id)
    if not fossa_payment:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Payment link does not exist."
        )
    fossa = await get_fossa(fossa_payment.fossa_id)
    if not fossa:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Unable to find fossa."
        )

    return fossa_renderer().TemplateResponse(
        "fossa/atm_receipt.html",
        {
            "request": request,
            "id": fossa_payment.id,
            "fossa_id": fossa_payment.fossa_id,
            "title": fossa.title,
            "payment_hash": fossa_payment.payment_hash,
            "sats": fossa_payment.sats,
            "lnurl": fossa_payment.payload,
        },
    )
