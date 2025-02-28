import base64
from http import HTTPStatus

import bolt11
from fastapi import APIRouter, Query, Request
from lnbits.core.crud import get_wallet
from lnbits.core.services import pay_invoice
from lnbits.utils.exchange_rates import fiat_amount_as_satoshis
from starlette.exceptions import HTTPException

from .crud import (
    create_fossa_payment,
    delete_atm_payment_link,
    get_fossa,
    get_fossa_payment,
    update_fossa_payment,
)
from .helpers import register_atm_payment, xor_decrypt
from .models import CreateFossaPayment

fossa_lnurl_router = APIRouter()


@fossa_lnurl_router.get(
    "/api/v1/lnurl/{device_id}",
    status_code=HTTPStatus.OK,
    name="fossa.lnurl_params",
)
async def fossa_lnurl_params(
    request: Request,
    device_id: str,
    p: str = Query(None),
    atm: str = Query(None),
):
    device = await get_fossa(device_id)
    if not device:
        return {
            "status": "ERROR",
            "reason": f"fossa {device_id} not found on this server",
        }

    if len(p) % 4 > 0:
        p += "=" * (4 - (len(p) % 4))

    data = base64.urlsafe_b64decode(p)
    try:
        pin, amount_in_cent = xor_decrypt(device.key.encode(), data)
    except Exception as exc:
        return {"status": "ERROR", "reason": str(exc)}

    price_msat = (
        await fiat_amount_as_satoshis(float(amount_in_cent) / 100, device.currency)
        if device.currency != "sat"
        else amount_in_cent
    )
    if price_msat is None:
        return {"status": "ERROR", "reason": "Price fetch error."}

    if atm:
        fossa_payment, price_msat = await register_atm_payment(device, p)
        if not fossa_payment:
            return {"status": "ERROR", "reason": "Payment already claimed."}
        return {
            "tag": "withdrawRequest",
            "callback": str(
                request.url_for("fossa.lnurl_callback", payment_id=fossa_payment.id)
            ),
            "k1": fossa_payment.payload,
            "minWithdrawable": price_msat,
            "maxWithdrawable": price_msat,
            "defaultDescription": f"{device.title} ID: {fossa_payment.id}",
        }
    price_msat = int(price_msat * ((device.profit / 100) + 1))

    fossa_payment = await create_fossa_payment(
        deviceid=device.id,
        payload=p,
        sats=price_msat * 1000,
        pin=int(pin),
        payhash="payment_hash",
    )
    if not fossa_payment:
        return {"status": "ERROR", "reason": "Could not create payment."}
    return {
        "tag": "payRequest",
        "callback": str(
            request.url_for("fossa.lnurl_callback", payment_id=fossa_payment.id)
        ),
        "minSendable": price_msat * 1000,
        "maxSendable": price_msat * 1000,
        "metadata": device.lnurlpay_metadata,
    }


@fossa_lnurl_router.get(
    "/api/v1/lnurl/cb/{payment_id}",
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
        return {"status": "ERROR", "reason": "fossa_payment not found."}
    if not pr:
        await delete_atm_payment_link(payment_id)
        return {"status": "ERROR", "reason": "No payment request."}
    device = await get_fossa(fossa_payment.deviceid)
    if not device:
        await delete_atm_payment_link(payment_id)
        return {"status": "ERROR", "reason": "fossa not found."}

    if fossa_payment.payload == fossa_payment.payhash:
        return {"status": "ERROR", "reason": "Payment already claimed."}

    if fossa_payment.payhash == "pending":
        return {
            "status": "ERROR",
            "reason": "Pending. If you are unable to withdraw contact vendor",
        }

    invoice = bolt11.decode(pr)
    if not invoice.payment_hash:
        await delete_atm_payment_link(payment_id)
        return {"status": "ERROR", "reason": "Not valid payment request."}
    if not invoice.payment_hash:
        await delete_atm_payment_link(payment_id)
        return {"status": "ERROR", "reason": "Not valid payment request."}
    wallet = await get_wallet(device.wallet)
    assert wallet
    if wallet.balance_msat < (int(fossa_payment.sats / 1000) + 100):
        await delete_atm_payment_link(payment_id)
        return {"status": "ERROR", "reason": "Not enough funds."}
    if fossa_payment.payload != k1:
        await delete_atm_payment_link(payment_id)
        return {"status": "ERROR", "reason": "Bad K1"}
    if fossa_payment.payhash != "payment_hash":
        return {"status": "ERROR", "reason": "Payment already claimed"}
    try:
        fossa_payment.payhash = "pending"
        fossa_payment_updated = await update_fossa_payment(
            CreateFossaPayment(**fossa_payment.dict(exclude={"timestamp"}))
        )
        assert fossa_payment_updated
        await pay_invoice(
            wallet_id=device.wallet,
            payment_request=pr,
            max_sat=int(fossa_payment_updated.sats) + 100,
            extra={"tag": "fossa_withdraw"},
        )
        fossa_payment.payhash = fossa_payment.payload
        fossa_payment_updated = await update_fossa_payment(
            CreateFossaPayment(**fossa_payment.dict(exclude={"timestamp"}))
        )
        assert fossa_payment_updated
        return {"status": "OK"}
    except HTTPException as e:
        return {"status": "ERROR", "reason": str(e)}
    except Exception as e:
        fossa_payment.payhash = "payment_hash"
        fossa_payment_updated = await update_fossa_payment(
            CreateFossaPayment(**fossa_payment.dict(exclude={"timestamp"}))
        )
        assert fossa_payment_updated
        return {"status": "ERROR", "reason": str(e)}
