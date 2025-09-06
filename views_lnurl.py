from http import HTTPStatus
from math import ceil

from bolt11 import decode as bolt11_decode
from fastapi import APIRouter, BackgroundTasks, Query, Request
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
from .models import FossaPayment

fossa_lnurl_router = APIRouter(prefix="/api/v1/lnurl")


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
    if len(payload) % 22 != 0:
        return LnurlErrorResponse(reason="Invalid payload length.")
    try:
        decrypted = aes_decrypt_payload(payload, fossa.key)
    except Exception as e:
        logger.debug(f"Error decrypting payload: {e}")
        return LnurlErrorResponse(reason="Invalid payload.")

    price_sat = (
        await fiat_amount_as_satoshis(float(decrypted.amount) / 100, fossa.currency)
        if fossa.currency != "sat"
        else ceil(float(decrypted.amount))
    )
    if price_sat is None:
        return LnurlErrorResponse(reason="Price fetch error.")

    price_sat = int(price_sat * ((fossa.profit / 100) + 1))
    amount_sats = await fossa.amount_to_sats(decrypted.amount)
    url = request.url_for("fossa.lnurl_params", fossa_id=fossa.id)
    lnurl_payload = str(lnurl_encode(str(url) + f"?p={payload}"))
    fossa_payment = await get_fossa_payment(payload)
    if not fossa_payment:
        fossa_payment = FossaPayment(
            id=payload,
            fossa_id=fossa.id,
            sats=price_sat,
            amount=amount_sats,
            pin=decrypted.pin,
            payload=lnurl_payload,
        )
        await create_fossa_payment(fossa_payment)
    else:
        if fossa_payment.payment_hash:
            return LnurlErrorResponse(reason="Payment already claimed.")

    url = request.url_for("fossa.lnurl_callback", payment_id=payload)
    callback = parse_obj_as(CallbackUrl, str(url))
    prepare_description = (
        f"{fossa.title} ID: {fossa_payment.id} ATM Fee: {fossa.profit}%"
    )
    return LnurlWithdrawResponse(
        callback=callback,
        k1=fossa_payment.id,
        minWithdrawable=MilliSatoshi(fossa_payment.amount * 1000),
        maxWithdrawable=MilliSatoshi(fossa_payment.amount * 1000),
        defaultDescription=prepare_description,
    )


@fossa_lnurl_router.get(
    "/cb/{payment_id}",
    status_code=HTTPStatus.OK,
    name="fossa.lnurl_callback",
)
async def lnurl_callback(
    payment_id: str,
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

    fossa_payment = await get_fossa_payment(payment_id)
    if not fossa_payment:
        return LnurlErrorResponse(reason="Payment not found.")
    if fossa_payment.payment_hash:
        return LnurlErrorResponse(reason="Payment already claimed.")
    fossa = await get_fossa(fossa_payment.fossa_id)
    if not fossa:
        return LnurlErrorResponse(reason="Fossa not found.")

    wallet = await get_wallet(fossa.wallet)
    if not wallet:
        return LnurlErrorResponse(reason="Wallet not found.")
    if wallet.balance < fossa_payment.amount:
        return LnurlErrorResponse(reason="Not enough funds in wallet.")

    try:
        # set to pending and pay invoice in background to prevent double spending
        fossa_payment.payment_hash = "pending"
        await update_fossa_payment(fossa_payment)

        async def _pay_invoice():
            payment = await pay_invoice(
                wallet_id=fossa.wallet,
                payment_request=pr,
                max_sat=int(fossa_payment.amount),
                extra={"tag": "fossa"},
            )
            fossa_payment.payment_hash = payment.payment_hash
            await update_fossa_payment(fossa_payment)

        background_tasks.add_task(_pay_invoice)
        return LnurlSuccessResponse()
    except Exception as e:
        fossa_payment.payment_hash = None
        await update_fossa_payment(fossa_payment)
        logger.error(f"Payment processing failed: {e}")
        return LnurlErrorResponse(reason="Payment processing failed.")
