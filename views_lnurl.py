from http import HTTPStatus

from bolt11 import decode as bolt11_decode
from fastapi import APIRouter, HTTPException, Query, Request
from lnbits.core.crud import get_wallet
from lnbits.core.services import pay_invoice
from lnbits.utils.exchange_rates import fiat_amount_as_satoshis
from lnurl import (
    CallbackUrl,
    LnurlErrorResponse,
    LnurlSuccessResponse,
    LnurlWithdrawResponse,
    MilliSatoshi,
)
from pydantic import parse_obj_as
from lnurl import encode as lnurl_encode
from loguru import logger

from .crud import (
    create_fossa_payment,
    get_fossa,
    get_fossa_payment,
    update_fossa_payment,
)
from .helpers import LnurlDecrypted, decrypt_payload
from .models import FossaPayment

fossa_lnurl_router = APIRouter(prefix="/api/v1/lnurl")


async def _validate_payload(payload: str, iv: str, key: str) -> LnurlDecrypted:
    payment = await get_fossa_payment(iv)
    if payment and payment.payment_hash:
        raise HTTPException(HTTPStatus.BAD_REQUEST, "Payment already claimed.")
    if payment:
        raise HTTPException(HTTPStatus.BAD_REQUEST, "Payment already registered.")
    try:
        return decrypt_payload(key, iv, payload)
    except Exception as e:
        logger.debug(f"Error decrypting payload: {e}")
        logger.debug(f"Payload: {payload}")
        raise HTTPException(HTTPStatus.BAD_REQUEST, "Invalid payload.") from e


@fossa_lnurl_router.get(
    "/{fossa_id}",
    status_code=HTTPStatus.OK,
    name="fossa.lnurl_params",
)
async def fossa_lnurl_params(
    request: Request,
    fossa_id: str,
    payload: str = Query(..., alias="p"),
    iv: str = Query(...),
):
    fossa = await get_fossa(fossa_id)
    if not fossa:
        raise HTTPException(HTTPStatus.NOT_FOUND, "fossa not found on this server")
    decrypted = await _validate_payload(payload, iv, fossa.key)
    if fossa.currency == "sat":
        price_sat = int(decrypted.amount)
    else:
        price_sat = await fiat_amount_as_satoshis(
            float(decrypted.amount) / 100, fossa.currency
        )
    price_sat = int(price_sat - ((price_sat / 100) * fossa.profit))
    url = request.url_for("fossa.lnurl_params", fossa_id=fossa.id)
    payload = str(lnurl_encode(str(url) + f"?p={payload}&iv={iv}"))
    fossa_payment = FossaPayment(
        id=iv,
        fossa_id=fossa.id,
        sats=price_sat,
        pin=decrypted.pin,
        payload=payload,
    )
    fossa_payment = await create_fossa_payment(fossa_payment)
    return {
        "tag": "withdrawRequest",
        "callback": str(request.url_for("fossa.lnurl_callback", fossa_id=fossa.id)),
        "k1": fossa_payment.id,
        "minWithdrawable": fossa_payment.sats * 1000,
        "maxWithdrawable": fossa_payment.sats * 1000,
        "defaultDescription": f"{fossa.title} ID: {fossa_payment.id}",
    }


@fossa_lnurl_router.get(
    "/cb/{fossa_id}",
    status_code=HTTPStatus.OK,
    name="fossa.lnurl_callback",
)
async def lnurl_callback(
    fossa_id: str,
    pr: str = Query(None),
    k1: str = Query(None),
):
    if not k1:
        raise HTTPException(HTTPStatus.BAD_REQUEST, "Missing K1")
    if not pr:
        raise HTTPException(HTTPStatus.BAD_REQUEST, "No payment request.")
    try:
        invoice = bolt11_decode(pr)
        if not invoice.payment_hash:
            raise ValueError("Not valid payment request.")
    except Exception as e:
        raise HTTPException(HTTPStatus.BAD_REQUEST, "Bad bolt11 invoice.") from e

    fossa = await get_fossa(fossa_id)
    if not fossa:
        raise HTTPException(HTTPStatus.NOT_FOUND, "Fossa not found.")
    fossa_payment = await get_fossa_payment(k1)
    if not fossa_payment:
        raise HTTPException(HTTPStatus.NOT_FOUND, "Fossa payment not found.")
    if fossa_payment.payment_hash:
        raise HTTPException(HTTPStatus.BAD_REQUEST, "Payment already claimed.")

    wallet = await get_wallet(fossa.wallet)
    if not wallet:
        raise HTTPException(HTTPStatus.NOT_FOUND, "Wallet not found.")
    if wallet.balance_msat < (int(fossa_payment.sats / 1000) + 100):
        raise HTTPException(HTTPStatus.BAD_REQUEST, "Not enough funds.")

    payment = await pay_invoice(
        wallet_id=fossa.wallet,
        payment_request=pr,
        max_sat=int(fossa_payment.sats) + 100,
        extra={"tag": "fossa_withdraw"},
    )
    fossa_payment.payment_hash = payment.payment_hash
    await update_fossa_payment(fossa_payment)
    return {"status": "OK"}
