import asyncio

import httpx
from lnbits.core.crud import get_wallet
from lnbits.core.models import Payment
from lnbits.core.services import websocket_updater
from lnbits.settings import settings
from lnbits.tasks import register_invoice_listener
from loguru import logger

from .crud import get_fossa, get_fossa_payment_by_hash, update_fossa_payment


async def wait_for_paid_invoices():
    invoice_queue = asyncio.Queue()
    register_invoice_listener(invoice_queue, "ext_fossa")

    while True:
        payment = await invoice_queue.get()
        await on_invoice_paid(payment)


async def on_invoice_paid(payment: Payment) -> None:
    logger.debug(f"Fossa received paid invoice: {payment}")
    if payment.extra.get("tag") != "boltz":
        return

    swap_id = payment.extra.get("swap_id")
    logger.debug(f"Boltz swap_id: {swap_id}")
    if swap_id:
        fossa_payment = await get_fossa_payment_by_hash("pending_swap_" + swap_id)
        if not fossa_payment:
            return
        fossa = await get_fossa(fossa_payment.fossa_id)
        if not fossa:
            return
        wallet = await get_wallet(fossa.wallet)
        if not wallet:
            return
        try:
            async with httpx.AsyncClient() as client:
                swap = await client.post(
                    url=f"http://{settings.host}:{settings.port}/boltz/api/v1/swap/status",
                    headers={"X-API-KEY": wallet.adminkey},
                    json={"swapId": swap_id},
                )
            if swap:
                fossa_payment.payment_hash = swap_id
                await update_fossa_payment(fossa_payment)
                await websocket_updater("pending_swap_" + swap_id, "Paid")
                return
        except Exception:
            return
