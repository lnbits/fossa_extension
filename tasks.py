import asyncio

from lnbits.core.models import Payment
from lnbits.core.services import websocket_updater
from lnbits.tasks import register_invoice_listener
from loguru import logger

from .crud import get_fossa_payment_by_hash, update_fossa_payment


async def wait_for_paid_invoices():
    invoice_queue = asyncio.Queue()
    register_invoice_listener(invoice_queue, "ext_fossa")

    while True:
        payment = await invoice_queue.get()
        await on_invoice_paid(payment)


async def on_invoice_paid(payment: Payment) -> None:

    if payment.extra.get("tag") != "boltz":
        return

    swap_id = payment.extra.get("swap_id")
    if swap_id:
        try:
            from ..boltz.views_api import api_swap_status

            swap = await api_swap_status(swap_id)
            if swap:
                payment = await get_fossa_payment_by_hash("pending_swap_" + swap_id)
                if not payment:
                    logger.error(
                        f"Boltz: could not find fossa payment for swap {swap_id}"
                    )
                    return
                payment.payment_hash = swap_id
                await update_fossa_payment(payment)
                await websocket_updater("pending_swap_" + swap_id, "Paid")
                return
        except Exception:
            return
