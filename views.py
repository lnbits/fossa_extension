from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from lnbits.core.crud import (
    get_installed_extensions,
    get_wallet,
)
from lnbits.core.models import User
from lnbits.decorators import check_user_exists
from lnbits.helpers import template_renderer

from .crud import get_fossa, get_fossa_payment
from .helpers import decrypt_payload, parse_lnurl_payload

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

    # decrypt the payload
    decrypted = decrypt_payload(fossa.key, lnurl_payload.iv, lnurl_payload.payload)
    price_sat = await fossa.amount_to_sats(decrypted.amount)

    # check if boltz payouts is enabled but also check the boltz extension is enabled
    if fossa.boltz:
        installed_extensions = await get_installed_extensions(active=True)
        for extension in installed_extensions:
            if extension.id == "boltz" and extension.active:
                fossa.boltz = False

    # get to determine if the payload has been used
    payment = await get_fossa_payment(lnurl_payload.iv)

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
            "payload": fossa_payment.payload,
            "sats": fossa_payment.sats,
            "lnurl": fossa_payment.payload,
        },
    )
