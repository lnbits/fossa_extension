from http import HTTPStatus

from bolt11 import decode as bolt11_decode
from fastapi import APIRouter, BackgroundTasks, Query, Request
from lnbits.core.crud import get_wallet
from lnbits.core.services import pay_invoice
from lnurl import (
    CallbackUrl,
    LnurlErrorResponse,
    LnurlSuccessResponse,
    LnurlWithdrawResponse,
    MilliSatoshi,
)
from lnurl import encode as lnurl_encode
from loguru import logger
from pydantic import parse_obj_as

from .crud import (
    create_fossa_payment,
    get_fossa,
    get_fossa_payment,
    update_fossa_payment,
)
from .helpers import aes_decrypt_payload
from .models import FossaPayment, LnurlDecrypted

fossa_lnurl_router = APIRouter(prefix="/api/v1/lnurl")


async def _validate_payload(payload: str, key: str) -> LnurlDecrypted:
    if len(payload) % 22 != 0:
        raise ValueError("Invalid payload length.")
    try:
        decrypted = aes_decrypt_payload(payload, key)
    except Exception as e:
        logger.debug(f"Error decrypting payload: {e}")
        logger.debug(f"Payload: {payload}")
        raise ValueError("Decryption failed.") from e
    payment = await get_fossa_payment(payload)
    if payment and payment.payment_hash:
        raise ValueError("Payment already claimed.")
    if payment:
        raise ValueError("Payment already exists.")
    return decrypted


@fossa_lnurl_router.get(
    "/{fossa_id}",
    status_code=HTTPStatus.OK,
    name="fossa.lnurl_params",
)
async def fossa_lnurl_params(
    request: Request,
    fossa_id: str,
    payload: str = Query(..., alias="p"),
) -> LnurlWithdrawResponse | LnurlErrorResponse:
    fossa = await get_fossa(fossa_id)
    if not fossa:
        return LnurlErrorResponse(reason="fossa not found on this server")

    try:
        decrypted = await _validate_payload(payload, fossa.key)
    except ValueError as e:
        return LnurlErrorResponse(reason=str(e))

    amount_sat = await fossa.amount_to_sats(decrypted.amount)
    url = request.url_for("fossa.lnurl_params", fossa_id=fossa.id)
    lnurl_payload = str(lnurl_encode(str(url) + f"?p={payload}"))
    fossa_payment = FossaPayment(
        id=payload,
        fossa_id=fossa.id,
        sats=amount_sat,
        amount=decrypted.amount,
        pin=decrypted.pin,
        payload=lnurl_payload,
    )
    fossa_payment = await create_fossa_payment(fossa_payment)
    url = request.url_for("fossa.lnurl_callback", fossa_id=fossa.id)
    callback = parse_obj_as(CallbackUrl, str(url))
    return LnurlWithdrawResponse(
        callback=callback,
        k1=fossa_payment.id,
        minWithdrawable=MilliSatoshi(fossa_payment.sats * 1000),
        maxWithdrawable=MilliSatoshi(fossa_payment.sats * 1000),
        defaultDescription=f"{fossa.title} ID: {fossa_payment.id}",
    )


@fossa_lnurl_router.get(
    "/cb/{fossa_id}",
    status_code=HTTPStatus.OK,
    name="fossa.lnurl_callback",
)
async def lnurl_callback(
    fossa_id: str,
    background_tasks: BackgroundTasks,
    pr: str = Query(None),
    k1: str = Query(None),
) -> LnurlErrorResponse | LnurlSuccessResponse:
    if not k1:
        return LnurlErrorResponse(reason="Missing K1")
    if not pr:
        return LnurlErrorResponse(reason="Missing payment request")
    try:
        _ = bolt11_decode(pr)
    except Exception:
        return LnurlErrorResponse(reason="Invalid payment request.")

    fossa = await get_fossa(fossa_id)
    if not fossa:
        return LnurlErrorResponse(reason="Fossa not found.")
    fossa_payment = await get_fossa_payment(k1)
    if not fossa_payment:
        return LnurlErrorResponse(reason="Payment not found.")
    if fossa_payment.payment_hash:
        return LnurlErrorResponse(reason="Payment already claimed.")

    wallet = await get_wallet(fossa.wallet)
    if not wallet:
        return LnurlErrorResponse(reason="Wallet not found.")
    if wallet.balance < fossa_payment.sats:
        return LnurlErrorResponse(reason="Not enough funds in wallet.")

    # set to pending and pay invoice in background to prevent double spending
    fossa_payment.payment_hash = "pending"
    await update_fossa_payment(fossa_payment)

    async def _pay_invoice():
        payment = await pay_invoice(
            wallet_id=fossa.wallet,
            payment_request=pr,
            max_sat=int(fossa_payment.sats) + 100,
            extra={"tag": "fossa"},
        )
        fossa_payment.payment_hash = payment.payment_hash
        await update_fossa_payment(fossa_payment)

    background_tasks.add_task(_pay_invoice)

    return LnurlSuccessResponse()
