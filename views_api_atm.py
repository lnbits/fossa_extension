from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from math import ceil

import bolt11
from fastapi import APIRouter, Depends, HTTPException
from lnbits.core.crud import get_user, get_wallet
from lnbits.core.models import SimpleStatus, WalletTypeInfo
from lnbits.core.services import pay_invoice
from lnbits.core.services.lnurl import get_pr_from_lnurl
from lnbits.decorators import require_admin_key
from lnbits.helpers import is_valid_email_address
from lnbits.utils.exchange_rates import fiat_amount_as_satoshis
from lnurl import url_decode

from .crud import (
    create_fossa_payment,
    delete_atm_payment_link,
    get_fossa,
    get_fossa_payment,
    get_fossa_payments,
    get_fossas,
    update_fossa_payment,
)
from .helpers import aes_decrypt_payload, parse_lnurl_payload
from .models import ONCHAIN_UNAVAILABLE_MESSAGE, FossaPayment

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
    fossa_payments = await get_fossa_payments(ids)

    # Loop through any attempting swaps and if they failed clear them after 10 minutes
    ten_minutes_ago = datetime.now(timezone.utc) - timedelta(minutes=10)
    for payment in fossa_payments:
        if (
            payment.payment_hash
            and payment.payment_hash.startswith("pending_swap_")
            and payment.timestamp < ten_minutes_ago
        ):
            payment.payment_hash = None
            await update_fossa_payment(payment)

    # get updated payments list
    return await get_fossa_payments(ids)


@fossa_api_atm_router.delete("/api/v1/atm/{atm_id}")
async def api_atm_payment_delete(
    atm_id: str, wallet: WalletTypeInfo = Depends(require_admin_key)
) -> None:
    fossa_payment = await get_fossa_payment(atm_id)
    if not fossa_payment:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="ATM payment does not exist."
        )
    fossa = await get_fossa(fossa_payment.fossa_id)
    if not fossa:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Fossa does not exist"
        )
    fetched_wallet = await get_wallet(fossa.wallet)
    if not fetched_wallet:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="Payment could not be deleted",
        )
    if fetched_wallet.user != wallet.wallet.user:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="Not your fossa")

    await delete_atm_payment_link(atm_id)


async def _validate_payment_request(pr: str, amount_msat: int) -> str:
    pr = pr.lower().strip()
    if pr.startswith("lnbc"):
        ln = pr
    elif pr.startswith("lnurl1") or is_valid_email_address(pr):
        try:
            ln = await get_pr_from_lnurl(pr, amount_msat)
        except Exception as exc:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail="Not valid LNURL Pay response",
            ) from exc
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


@fossa_api_atm_router.get("/api/v1/ln/{lnurl}/{withdraw_request}")
async def get_fossa_payment_lightning(
    lnurl: str, withdraw_request: str
) -> SimpleStatus:
    """
    Handle Lightning payments for atms via invoice, lnaddress, lnurlp (withdraw_request)
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

    try:
        decrypted = aes_decrypt_payload(lnurl_payload.payload, fossa.key)
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail="Invalid payload."
        ) from e
    amount_sat = await fossa.amount_to_sats(decrypted.amount)

    if wallet.balance < amount_sat:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail="Not enough funds in wallet"
        )
    price_sat = (
        await fiat_amount_as_satoshis(float(decrypted.amount) / 100, fossa.currency)
        if fossa.currency != "sat"
        else ceil(float(decrypted.amount))
    )
    if price_sat is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="Price fetch error.",
        )

    price_sat = int(price_sat * ((fossa.profit / 100) + 1))
    ln = await _validate_payment_request(withdraw_request, amount_sat * 1000)
    fossa_payment = await get_fossa_payment(lnurl_payload.payload)
    if not fossa_payment:
        fossa_payment = FossaPayment(
            id=lnurl_payload.payload,
            fossa_id=fossa.id,
            sats=price_sat,
            amount=amount_sat,
            pin=decrypted.pin,
            payload=str(url_decode(lnurl)),
            payment_hash="pending",
        )
        await create_fossa_payment(fossa_payment)
    else:
        if fossa_payment.payment_hash:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail="Payment already claimed.",
            )
    try:
        # set to pending and pay invoice in background to prevent double spending
        fossa_payment.payment_hash = "pending"
        await update_fossa_payment(fossa_payment)
        payment = await pay_invoice(
            wallet_id=fossa.wallet,
            payment_request=ln,
            extra={"tag": "fossa", "id": fossa_payment.id},
        )
        assert payment.payment_hash
        # successful payment, update fossa_payment
        fossa_payment.payment_hash = payment.payment_hash
        await update_fossa_payment(fossa_payment)

        return SimpleStatus(success=True, message="Payment successful")
    except Exception as err:
        # unsuccessful payment, release fossa_payment
        fossa_payment.payment_hash = None
        await update_fossa_payment(fossa_payment)
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="withdraw failed, try again later",
        ) from err


@fossa_api_atm_router.get("/api/v1/boltz/{lnurl}/{onchain_liquid}/{address}")
async def get_fossa_payment_boltz(lnurl: str, onchain_liquid: str, address: str):
    # Retain the URL so old clients receive an explicit error without initiating a swap.
    raise HTTPException(
        status_code=HTTPStatus.GONE,
        detail=ONCHAIN_UNAVAILABLE_MESSAGE,
    )
