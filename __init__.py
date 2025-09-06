import asyncio
from fastapi import APIRouter

from .crud import db
from .views import fossa_generic_router
from .views_api import fossa_api_router
from .views_api_atm import fossa_api_atm_router
from .views_lnurl import fossa_lnurl_router

from .tasks import wait_for_paid_invoices

from loguru import logger

fossa_ext: APIRouter = APIRouter(prefix="/fossa", tags=["fossa"])
fossa_ext.include_router(fossa_generic_router)
fossa_ext.include_router(fossa_api_router)
fossa_ext.include_router(fossa_lnurl_router)
fossa_ext.include_router(fossa_api_atm_router)

fossa_static_files = [
    {
        "path": "/fossa/static",
        "name": "fossa_static",
    }
]

scheduled_tasks: list[asyncio.Task] = []

def fossa_stop():
    for task in scheduled_tasks:
        try:
            task.cancel()
        except Exception as ex:
            logger.warning(ex)

def fossa_start():
    from lnbits.tasks import create_permanent_unique_task

    paid_invoices = create_permanent_unique_task(
        "ext_boltz_paid_invoices", wait_for_paid_invoices
    )
    scheduled_tasks.append(paid_invoices)


__all__ = ["db", "fossa_ext", "fossa_start", "fossa_static_files", "fossa_stop"]