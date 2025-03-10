from http import HTTPStatus

import bolt11
import httpx
from fastapi import APIRouter, Depends, HTTPException
from lnbits.core.crud import get_user, get_wallet
from lnbits.core.models import SimpleStatus, WalletTypeInfo
from lnbits.core.services import pay_invoice
from lnbits.decorators import (
    check_user_extension_access,
    require_admin_key,
)
from lnbits.helpers import is_valid_email_address
from lnbits.settings import settings
from lnbits.utils.exchange_rates import fiat_amount_as_satoshis
from lnurl import LnurlPayActionResponse, LnurlPayResponse
from lnurl import execute_pay_request as lnurl_execute_pay_request
from lnurl import handle as lnurl_handle

from .crud import (
    create_fossa_payment,
    delete_atm_payment_link,
    get_fossa,
    get_fossa_payment,
    get_fossa_payments,
    get_fossas,
)
from .helpers import decrypt_payload, parse_lnurl_payload
from .models import FossaPayment

fossa_api_atm_router = APIRouter()


@fossa_api_atm_router.get("/api/v1/atm")
async def api_atm_payments_retrieve(
    wallet: WalletTypeInfo = Depends(require_admin_key),
) -> list[FossaPayment]:
    user = await get_user(wallet.wallet.user)
    if not user:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="User does not exist"
        )
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
    if not invoice.amount_msat or int(invoice.amount_msat) != amount_msat:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Request is not the same as withdraw amount",
        )

    return ln


@fossa_api_atm_router.get("/api/v1/ln/{lnurl}/{pr}")
async def get_fossa_payment_lightning(lnurl: str, pr: str) -> SimpleStatus:
    """
    Handle Lightning payments for atms via invoice, lnaddress, lnurlp.
    """
    lnurl_payload = parse_lnurl_payload(lnurl)
    fossa = await get_fossa(lnurl_payload.fossa_id)
    if not fossa:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Fossa does not exist"
        )
    wallet = await get_wallet(fossa.wallet)
    if not wallet:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="Wallet does not exist.",
        )

    decrypted = decrypt_payload(fossa.key, lnurl_payload.iv, lnurl_payload.payload)

    # Determine the price in msat
    if fossa.currency != "sat":
        amount_msat = (
            await fiat_amount_as_satoshis(decrypted.amount / 100, fossa.currency) * 1000
        )
    else:
        amount_msat = int(decrypted.amount) * 1000

    if wallet.balance_msat < amount_msat:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail="Not enough funds in wallet"
        )

    ln = await _validate_payment_request(pr, amount_msat)

    payment_id = lnurl_payload.iv
    payment = await pay_invoice(
        wallet_id=fossa.wallet,
        payment_request=ln,
        extra={"tag": "fossa", "id": payment_id},
    )
    fossa_payment = FossaPayment(
        id=payment_id,
        fossa_id=fossa.id,
        sats=int(amount_msat / 1000),
        pin=decrypted.pin,
        payload=lnurl,
        payment_hash=payment.payment_hash,
    )
    await create_fossa_payment(fossa_payment)
    return SimpleStatus(success=True, message="Payment successful")


@fossa_api_atm_router.get("/api/v1/boltz/{lnurl}/{onchain_liquid}/{address}")
async def get_fossa_payment_boltz(lnurl: str, onchain_liquid: str, address: str):
    """
    Handle Boltz payments for atms.
    """
    lnurl_payload = parse_lnurl_payload(lnurl)
    fossa = await get_fossa(lnurl_payload.fossa_id)
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
    access = await check_user_extension_access(wallet.user, "boltz")
    if not access.success:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="Boltz extension not enabled",
        )
    decrypted = decrypt_payload(fossa.key, lnurl_payload.iv, lnurl_payload.payload)
    amount_sats = int(decrypted.amount)
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url=f"http://{settings.host}:{settings.port}/boltz/api/v1/swap/reverse",
            headers={"X-API-KEY": wallet.adminkey},
            json={
                "wallet": fossa.wallet,
                "asset": onchain_liquid.replace("temp", "/"),
                "amount": amount_sats,
                "direction": "send",
                "instant_settlement": True,
                "onchain_address": address,
                "feerate": False,
                "feerate_value": 0,
            },
        )
        response.raise_for_status()
        resp = response.json()
        # TODO get payment_hash from boltz reverse swap
        print("BOLTZ RESPONSE")
        print(resp)
        fossa_payment = FossaPayment(
            id=lnurl_payload.iv,
            fossa_id=fossa.id,
            sats=amount_sats,
            pin=decrypted.pin,
            payload=lnurl,
            payment_hash=resp.get("payment_hash", "invalid_boltz_payment_hash"),
        )
        await create_fossa_payment(fossa_payment)
        return resp
