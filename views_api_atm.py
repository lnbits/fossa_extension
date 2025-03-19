from http import HTTPStatus

import bolt11
import httpx
from fastapi import APIRouter, Depends, HTTPException
from lnbits.core.crud import get_user, get_wallet
from lnbits.core.models import WalletTypeInfo
from lnbits.core.services import pay_invoice
from lnbits.decorators import (
    check_user_extension_access,
    require_admin_key,
    require_invoice_key,
)
from lnbits.helpers import is_valid_email_address
from lnbits.settings import settings
from lnurl import LnurlPayActionResponse, LnurlPayResponse
from lnurl import execute_pay_request as lnurl_execute_pay_request
from lnurl import handle as lnurl_handle

from .crud import (
    delete_atm_payment_link,
    get_fossa,
    get_fossa_payment,
    get_fossa_payments,
    get_fossas,
    update_fossa_payment,
)
from .helpers import register_atm_payment
from .models import FossaPayment

fossa_api_atm_router = APIRouter()


@fossa_api_atm_router.get("/api/v1/atm")
async def api_atm_payments_retrieve(
    wallet: WalletTypeInfo = Depends(require_invoice_key),
) -> list[FossaPayment]:
    user = await get_user(wallet.wallet.user)
    assert user, "Fossa cannot retrieve user"
    fossas = await get_fossas(user.wallet_ids)
    ids = []
    for fossa in fossas:
        ids.append(fossa.id)
    return await get_fossa_payments(ids)


@fossa_api_atm_router.delete(
    "/api/v1/atm/{atm_id}", dependencies=[Depends(require_admin_key)]
)
async def api_atm_payment_delete(atm_id: str):
    fossa = await get_fossa_payment(atm_id)
    if not fossa:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="ATM payment does not exist."
        )

    await delete_atm_payment_link(atm_id)


async def _validate_payment_request(pr: str, amount_msat: int) -> str:
    pr = pr.lower().strip()
    if pr.startswith("lnbc"):
        ln = pr
    elif pr.startswith("lnurl1") or is_valid_email_address(pr):
        res = await lnurl_handle(pr)
        if not isinstance(res, LnurlPayResponse):
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN, detail="Not valid LNURL Pay response"
            )
        res2 = await lnurl_execute_pay_request(
            res, msat=str(amount_msat), user_agent=settings.user_agent
        )
        if not isinstance(res2, LnurlPayActionResponse):
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail="Not valid LNURL Pay action response",
            )
        ln = res2.pr
    else:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail="Not valid payment request"
        )
    # validate invoice amount
    invoice = bolt11.decode(ln)
    if not invoice.payment_hash:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail="Not valid payment request"
        )
    if not invoice.payment_hash:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail="Not valid payment request"
        )
    if not invoice.amount_msat or int(invoice.amount_msat) != amount_msat:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Request is not the same as withdraw amount",
        )

    return ln


@fossa_api_atm_router.get("/api/v1/ln/{fossa_id}/{p}/{ln}")
async def get_fossa_payment_lightning(fossa_id: str, p: str, ln: str) -> str:
    """
    Handle Lightning payments for atms via invoice, lnaddress, lnurlp.
    """

    fossa = await get_fossa(fossa_id)
    if not fossa:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="fossa does not exist"
        )

    wallet = await get_wallet(fossa.wallet)
    if not wallet:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="Wallet does not exist connected to atm, payment could not be made",
        )

    fossa_payment, price_msat = await register_atm_payment(fossa, p)
    if not fossa_payment or not price_msat:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Payment already claimed."
        )

    ln = await _validate_payment_request(ln, price_msat)

    # Finally log the payment and make the payment
    fossa_payment.payment_hash = fossa_payment.payload
    await update_fossa_payment(fossa_payment)

    await pay_invoice(
        wallet_id=fossa.wallet,
        payment_request=ln,
        max_sat=price_msat,
        extra={"tag": "fossa", "id": fossa_payment.id},
    )

    return fossa_payment.id


@fossa_api_atm_router.get(
    "/api/v1/boltz/{fossa_id}/{payload}/{onchain_liquid}/{address}"
)
async def get_fossa_payment_boltz(
    fossa_id: str, payload: str, onchain_liquid: str, address: str
):
    """
    Handle Boltz payments for atms.
    """
    fossa = await get_fossa(fossa_id)
    if not fossa:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="fossa does not exist"
        )

    fossa_payment, _ = await register_atm_payment(fossa, payload)
    assert fossa_payment
    if fossa_payment == "ERROR":
        return fossa_payment
    if fossa_payment.payload == fossa_payment.payment_hash:
        return {"status": "ERROR", "reason": "Payment already claimed."}
    if fossa_payment.payment_hash == "pending":
        return {
            "status": "ERROR",
            "reason": "Pending. If you are unable to withdraw contact vendor",
        }
    wallet = await get_wallet(fossa.wallet)
    if not wallet:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="Wallet does not exist connected to atm, payment could not be made",
        )
    access = await check_user_extension_access(wallet.user, "boltz")
    if not access.success:
        return {"status": "ERROR", "reason": "Boltz not enabled"}

    data = {
        "wallet": fossa.wallet,
        "asset": onchain_liquid.replace("temp", "/"),
        "amount": fossa_payment.sats,
        "direction": "send",
        "instant_settlement": True,
        "onchain_address": address,
        "feerate": False,
        "feerate_value": 0,
    }

    try:
        fossa_payment.payload = payload
        fossa_payment.payment_hash = "pending"
        fossa_payment = await update_fossa_payment(fossa_payment)
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url=f"http://{settings.host}:{settings.port}/boltz/api/v1/swap/reverse",
                headers={"X-API-KEY": wallet.adminkey},
                json=data,
            )
            fossa_payment.payment_hash = fossa_payment.payload
            fossa_payment = await update_fossa_payment(fossa_payment)
            resp = response.json()
            return resp
    except Exception as exc:
        fossa_payment.payment_hash = "payment_hash"
        await update_fossa_payment(fossa_payment)
        return {"status": "ERROR", "reason": str(exc)}
