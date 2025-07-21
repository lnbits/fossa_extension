import base64
from http import HTTPStatus

import bolt11
from fastapi import APIRouter, Query, Request
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

from .crud import (
    delete_atm_payment_link,
    get_fossa,
    get_fossa_payment,
    update_fossa_payment,
)
from .helpers import register_atm_payment, xor_decrypt

fossa_lnurl_router = APIRouter(prefix="/api/v1/lnurl")


@fossa_lnurl_router.get(
    "/{fossa_id}",
    status_code=HTTPStatus.OK,
    name="fossa.lnurl_params",
)
async def fossa_lnurl_params(
    request: Request,
    fossa_id: str,
    p: str = Query(None),
) -> LnurlWithdrawResponse | LnurlErrorResponse:
    fossa = await get_fossa(fossa_id)
    if not fossa:
        return LnurlErrorResponse(reason=f"fossa {fossa_id} not found on this server")

    if len(p) % 4 > 0:
        p += "=" * (4 - (len(p) % 4))

    data = base64.urlsafe_b64decode(p)
    try:
        _, amount_in_cent = xor_decrypt(fossa.key.encode(), data)
    except Exception:
        return LnurlErrorResponse(reason="Invalid payload.")

    price_msat = (
        await fiat_amount_as_satoshis(float(amount_in_cent) / 100, fossa.currency)
        if fossa.currency != "sat"
        else amount_in_cent
    )
    if price_msat is None:
        return LnurlErrorResponse(reason="Price fetch error.")

    fossa_payment, price_msat = await register_atm_payment(fossa, p)
    if not fossa_payment or not price_msat:
        return LnurlErrorResponse(reason="Payment already claimed.")

    url = request.url_for("fossa.lnurl_callback", payment_id=fossa_payment.id)
    callback_url = parse_obj_as(CallbackUrl, str(url))
    return LnurlWithdrawResponse(
        callback=callback_url,
        k1=fossa_payment.payload,
        minWithdrawable=MilliSatoshi(price_msat),
        maxWithdrawable=MilliSatoshi(price_msat),
        defaultDescription=f"{fossa.title} ID: {fossa_payment.id}",
    )


@fossa_lnurl_router.get(
    "/cb/{payment_id}",
    status_code=HTTPStatus.OK,
    name="fossa.lnurl_callback",
)
async def lnurl_callback(
    payment_id: str,
    pr: str = Query(None),
    k1: str = Query(None),
) -> LnurlErrorResponse | LnurlSuccessResponse:
    fossa_payment = await get_fossa_payment(payment_id)
    if not fossa_payment:
        return LnurlErrorResponse(reason="fossa_payment not found.")
    if not pr:
        return LnurlErrorResponse(reason="No payment request provided.")
    fossa = await get_fossa(fossa_payment.fossa_id)
    if not fossa:
        await delete_atm_payment_link(payment_id)
        return LnurlErrorResponse(reason="Fossa not found.")

    if fossa_payment.payload == fossa_payment.payment_hash:
        return LnurlErrorResponse(reason="Payment already claimed.")

    if fossa_payment.payment_hash == "pending":
        return LnurlErrorResponse(reason="Payment is pending.")

    invoice = bolt11.decode(pr)
    if not invoice.payment_hash:
        await delete_atm_payment_link(payment_id)
        return LnurlErrorResponse(reason="Invalid payment request.")
    wallet = await get_wallet(fossa.wallet)
    assert wallet
    if wallet.balance_msat < (int(fossa_payment.sats / 1000) + 100):
        await delete_atm_payment_link(payment_id)
        return LnurlErrorResponse(reason="Not enough funds.")
    if fossa_payment.payload != k1:
        await delete_atm_payment_link(payment_id)
        return LnurlErrorResponse(reason="Bad K1")
    if fossa_payment.payment_hash != "payment_hash":
        return LnurlErrorResponse(reason="Payment already claimed.")
    try:
        fossa_payment.payment_hash = "pending"
        fossa_payment = await update_fossa_payment(fossa_payment)
        await pay_invoice(
            wallet_id=fossa.wallet,
            payment_request=pr,
            max_sat=int(fossa_payment.sats) + 100,
            extra={"tag": "fossa_withdraw"},
        )
        fossa_payment.payment_hash = fossa_payment.payload
        fossa_payment = await update_fossa_payment(fossa_payment)
        return LnurlSuccessResponse()
    except Exception as e:
        fossa_payment.payment_hash = "payment_hash"
        fossa_payment = await update_fossa_payment(fossa_payment)
        return LnurlErrorResponse(reason=str(e))
