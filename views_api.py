from http import HTTPStatus

import bolt11
import httpx
from fastapi import APIRouter, Depends, HTTPException
from lnbits.core.crud import get_user, get_wallet
from lnbits.core.models import WalletTypeInfo
from lnbits.core.services import pay_invoice
from lnbits.core.views.api import api_lnurlscan
from lnbits.decorators import (
    check_user_extension_access,
    require_admin_key,
    require_invoice_key,
)
from lnbits.settings import settings
from lnurl import encode as lnurl_encode
from loguru import logger

from .crud import (
    create_fossa,
    delete_atm_payment_link,
    delete_fossa,
    get_fossa,
    get_fossa_payment,
    get_fossa_payments,
    get_fossas,
    update_fossa,
    update_fossa_payment,
)
from .helpers import register_atm_payment
from .models import CreateFossa, Fossa, FossaPayment, Lnurlencode

fossa_api_router = APIRouter(prefix="/api/v1")


@fossa_api_router.get("")
async def api_fossas_retrieve(
    key_info: WalletTypeInfo = Depends(require_invoice_key),
) -> list[Fossa]:
    user = await get_user(key_info.wallet.user)
    assert user, "Fossa cannot retrieve user"
    return await get_fossas(user.wallet_ids)


@fossa_api_router.get("/{fossa_id}", dependencies=[Depends(require_invoice_key)])
async def api_fossa_retrieve(fossa_id: str) -> Fossa:
    fossa = await get_fossa(fossa_id)
    if not fossa:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="fossa does not exist"
        )
    return fossa


@fossa_api_router.post("", dependencies=[Depends(require_admin_key)])
async def api_fossa_create(data: CreateFossa) -> Fossa:
    return await create_fossa(data)


@fossa_api_router.put("/{fossa_id}", dependencies=[Depends(require_admin_key)])
async def api_fossa_update(data: CreateFossa, fossa_id: str) -> Fossa:
    fossa = await get_fossa(fossa_id)
    if not fossa:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Fossa does not exist."
        )
    for k, v in data.dict().items():
        setattr(fossa, k, v)
    return await update_fossa(fossa)


@fossa_api_router.delete("/fossa_id}", dependencies=[Depends(require_admin_key)])
async def api_fossa_delete(fossa_id: str):
    fossa = await get_fossa(fossa_id)
    if not fossa:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Fossa does not exist."
        )

    await delete_fossa(fossa_id)


#########ATM API#########


@fossa_api_router.get("/api/v1/atm")
async def api_atm_payments_retrieve(
    wallet: WalletTypeInfo = Depends(require_invoice_key),
) -> list[FossaPayment]:
    user = await get_user(wallet.wallet.user)
    assert user, "Fossa cannot retrieve user"
    fossas = await get_fossas(user.wallet_ids)
    deviceids = []
    for fossa in fossas:
        deviceids.append(fossa.id)
    return await get_fossa_payments(deviceids)


@fossa_api_router.post(
    "/api/v1/lnurlencode", dependencies=[Depends(require_invoice_key)]
)
async def api_lnurlencode(data: Lnurlencode):
    lnurl = lnurl_encode(data.url)
    logger.debug(lnurl)
    if not lnurl:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Lnurl could not be encoded."
        )
    return lnurl


@fossa_api_router.delete(
    "/api/v1/atm/{atm_id}", dependencies=[Depends(require_admin_key)]
)
async def api_atm_payment_delete(atm_id: str):
    fossa = await get_fossa_payment(atm_id)
    if not fossa:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="ATM payment does not exist."
        )

    await delete_atm_payment_link(atm_id)


@fossa_api_router.get("/api/v1/ln/{fossa_id}/{p}/{ln}")
async def get_fossa_payment_lightning(fossa_id: str, p: str, ln: str) -> str:
    """
    Handle Lightning payments for atms via invoice, lnaddress, lnurlp.
    """
    ln = ln.strip().lower()

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
    if not fossa_payment:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Payment already claimed."
        )

    # If its an lnaddress or lnurlp get the request from callback
    elif ln[:5] == "lnurl" or "@" in ln and "." in ln.split("@")[-1]:
        data = await api_lnurlscan(ln)
        logger.debug(data)
        if data.get("status") == "ERROR":
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST, detail=data.get("reason")
            )
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url=f"{data['callback']}?amount={fossa_payment.sats * 1000}"
            )
            if response.status_code != 200:
                raise HTTPException(
                    status_code=HTTPStatus.BAD_REQUEST,
                    detail="Could not get callback from lnurl",
                )
            ln = response.json()["pr"]

    # If just an invoice
    elif ln[:4] == "lnbc":
        ln = ln

    # If ln is gibberish, return an error
    else:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="""
            Wrong format for payment, could not be made.
            Use LNaddress or LNURLp
            """,
        )

    # If its an invoice check its a legit invoice
    if ln[:4] == "lnbc":
        invoice = bolt11.decode(ln)
        if not invoice.payment_hash:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN, detail="Not valid payment request"
            )
        if not invoice.payment_hash:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN, detail="Not valid payment request"
            )
        if (
            not invoice.amount_msat
            or int(invoice.amount_msat / 1000) != fossa_payment.sats
        ):
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail="Request is not the same as withdraw amount",
            )

    # Finally log the payment and make the payment
    try:
        fossa_payment, price_msat = await register_atm_payment(fossa, p)
        assert fossa_payment
        fossa_payment.payhash = fossa_payment.payload
        await update_fossa_payment(fossa_payment)
        if ln[:4] == "lnbc":
            await pay_invoice(
                wallet_id=fossa.wallet,
                payment_request=ln,
                max_sat=price_msat,
                extra={"tag": "fossa", "id": fossa_payment.id},
            )
    except Exception as exc:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail=f"{exc!s}"
        ) from exc

    return fossa_payment.id


@fossa_api_router.get("/api/v1/boltz/{fossa_id}/{payload}/{onchain_liquid}/{address}")
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
    if fossa_payment.payload == fossa_payment.payhash:
        return {"status": "ERROR", "reason": "Payment already claimed."}
    if fossa_payment.payhash == "pending":
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
        fossa_payment.payhash = "pending"
        fossa_payment_updated = await update_fossa_payment(fossa_payment)
        assert fossa_payment_updated
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url=f"http://{settings.host}:{settings.port}/boltz/api/v1/swap/reverse",
                headers={"X-API-KEY": wallet.adminkey},
                json=data,
            )
            fossa_payment.payhash = fossa_payment.payload
            fossa_payment_updated = await update_fossa_payment(fossa_payment)
            assert fossa_payment_updated
            resp = response.json()
            return resp
    except Exception as exc:
        fossa_payment.payhash = "payment_hash"
        fossa_payment_updated = await update_fossa_payment(fossa_payment)
        assert fossa_payment_updated
        return {"status": "ERROR", "reason": str(exc)}
