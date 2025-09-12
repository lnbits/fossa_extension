from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException
from lnbits.core.crud import get_user
from lnbits.core.models import WalletTypeInfo
from lnbits.decorators import (
    require_admin_key,
    require_invoice_key,
)

from .crud import (
    create_fossa,
    delete_fossa,
    get_fossa,
    get_fossas,
    update_fossa,
)
from .models import CreateFossa, Fossa

fossa_api_router = APIRouter()


@fossa_api_router.get("/api/v1/fossa")
async def api_fossas_retrieve(
    key_info: WalletTypeInfo = Depends(require_invoice_key),
) -> list[Fossa]:
    user = await get_user(key_info.wallet.user)
    assert user, "Fossa cannot retrieve user"
    return await get_fossas(user.wallet_ids)


@fossa_api_router.get("/api/v1/fossa/{fossa_id}")
async def api_fossa_retrieve(
    fossa_id: str, wallet: WalletTypeInfo = Depends(require_invoice_key)
) -> Fossa:
    fossa = await get_fossa(fossa_id)
    if not fossa:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="fossa does not exist"
        )
    if fossa.wallet != wallet.wallet.id:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="Not your fossa")
    return fossa


@fossa_api_router.post("/api/v1/fossa", dependencies=[Depends(require_admin_key)])
async def api_fossa_create(data: CreateFossa) -> Fossa:
    return await create_fossa(data)


@fossa_api_router.put("/api/v1/fossa/{fossa_id}")
async def api_fossa_update(
    data: CreateFossa,
    fossa_id: str,
    wallet: WalletTypeInfo = Depends(require_admin_key),
) -> Fossa:
    fossa = await get_fossa(fossa_id)
    if not fossa:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Fossa does not exist."
        )
    if fossa.wallet != wallet.wallet.id:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="Not your fossa")
    for k, v in data.dict().items():
        setattr(fossa, k, v)
    return await update_fossa(fossa)


@fossa_api_router.delete("/api/v1/fossa/{fossa_id}")
async def api_fossa_delete(
    fossa_id: str, wallet: WalletTypeInfo = Depends(require_admin_key)
):
    fossa = await get_fossa(fossa_id)
    if not fossa:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Fossa does not exist."
        )
    if fossa.wallet != wallet.wallet.id:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="Not your fossa")

    await delete_fossa(fossa_id)
