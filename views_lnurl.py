import base64
from http import HTTPStatus

import bolt11
from fastapi import APIRouter, Query, Request
from lnbits.core.crud import get_wallet
from lnbits.core.services import pay_invoice
from lnbits.lnurl import LnurlErrorResponseHandler
from lnbits.utils.exchange_rates import fiat_amount_as_satoshis
from starlette.exceptions import HTTPException

from .crud import (
    delete_atm_payment_link,
    get_fossa,
    get_fossa_payment,
    update_fossa_payment,
)
from .helpers import register_atm_payment, xor_decrypt

fossa_lnurl_router = APIRouter(prefix="/api/v1/lnurl")
fossa_lnurl_router.route_class = LnurlErrorResponseHandler


@fossa_lnurl_router.get(
    "/{fossa_id}",
    status_code=HTTPStatus.OK,
    name="fossa.lnurl_params",
)
async def fossa_lnurl_params(
    request: Request,
    fossa_id: str,
    p: str = Query(None),
):
    fossa = await get_fossa(fossa_id)
    if not fossa:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=f"fossa {fossa_id} not found on this server",
        )

    if len(p) % 4 > 0:
        p += "=" * (4 - (len(p) % 4))

    data = base64.urlsafe_b64decode(p)
    try:
        _, amount_in_cent = xor_decrypt(fossa.key.encode(), data)
    except Exception as exc:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail="Invalid payload."
        ) from exc

    price_msat = (
        await fiat_amount_as_satoshis(float(amount_in_cent) / 100, fossa.currency)
        if fossa.currency != "sat"
        else amount_in_cent
    )
    if price_msat is None:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail="Price fetch error."
        )

    fossa_payment, price_msat = await register_atm_payment(fossa, p)
    if not fossa_payment:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail="Payment already claimed."
        )
    return {
        "tag": "withdrawRequest",
        "callback": str(
            request.url_for("fossa.lnurl_callback", payment_id=fossa_payment.id)
        ),
        "k1": fossa_payment.payload,
        "minWithdrawable": price_msat,
        "maxWithdrawable": price_msat,
        "defaultDescription": f"{fossa.title} ID: {fossa_payment.id}",
    }


@fossa_lnurl_router.get(
    "/cb/{payment_id}",
    status_code=HTTPStatus.OK,
    name="fossa.lnurl_callback",
)
async def lnurl_callback(
    payment_id: str,
    pr: str = Query(None),
    k1: str = Query(None),
):
    fossa_payment = await get_fossa_payment(payment_id)
    if not fossa_payment:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="fossa_payment not found.",
        )
    if not pr:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="No payment request.",
        )
    fossa = await get_fossa(fossa_payment.fossa_id)
    if not fossa:
        await delete_atm_payment_link(payment_id)
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="fossa not found.",
        )

    if fossa_payment.payload == fossa_payment.payment_hash:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail="Payment already claimed."
        )

    if fossa_payment.payment_hash == "pending":
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="Pending. If you are unable to withdraw contact vendor",
        )

    invoice = bolt11.decode(pr)
    if not invoice.payment_hash:
        await delete_atm_payment_link(payment_id)
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail="Not valid payment request."
        )
    wallet = await get_wallet(fossa.wallet)
    assert wallet
    if wallet.balance_msat < (int(fossa_payment.sats / 1000) + 100):
        await delete_atm_payment_link(payment_id)
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail="Not enough funds."
        )
    if fossa_payment.payload != k1:
        await delete_atm_payment_link(payment_id)
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="Bad K1")
    if fossa_payment.payment_hash != "payment_hash":
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail="Payment already claimed."
        )
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
        return {"status": "OK"}
    except HTTPException as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        fossa_payment.payment_hash = "payment_hash"
        fossa_payment = await update_fossa_payment(fossa_payment)
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e)) from e
