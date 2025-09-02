
import shortuuid
from lnbits.db import Database
from lnbits.helpers import urlsafe_short_hash

from .models import CreateFossa, Fossa, FossaPayment

db = Database("ext_fossa")


async def create_fossa(data: CreateFossa) -> Fossa:
    fossa_id = shortuuid.uuid()[:5]
    fossa_key = urlsafe_short_hash()[:16]
    fossa = Fossa(
        id=fossa_id,
        key=fossa_key,
        title=data.title,
        wallet=data.wallet,
        profit=data.profit,
        currency=data.currency,
        boltz=data.boltz,
    )
    await db.insert("fossa.fossa", fossa)
    return fossa


async def update_fossa(fossa: Fossa) -> Fossa:
    await db.update("fossa.fossa", fossa)
    return fossa


async def get_fossa(fossa_id: str) -> Fossa | None:
    return await db.fetchone(
        "SELECT * FROM fossa.fossa WHERE id = :id",
        {"id": fossa_id},
        Fossa,
    )


async def get_fossas(wallet_ids: list[str]) -> list[Fossa]:
    q = ",".join([f"'{w}'" for w in wallet_ids])
    return await db.fetchall(
        f"""
        SELECT * FROM fossa.fossa WHERE wallet IN ({q}) ORDER BY id
        """,
        model=Fossa,
    )


async def delete_fossa(fossa_id: str) -> None:
    await db.execute("DELETE FROM fossa.fossa WHERE id = :id", {"id": fossa_id})


async def create_fossa_payment(fossa_payment: FossaPayment) -> FossaPayment:
    await db.insert("fossa.fossa_payment", fossa_payment)
    return fossa_payment


async def update_fossa_payment(fossa_payment: FossaPayment) -> FossaPayment:
    await db.update("fossa.fossa_payment", fossa_payment)
    return fossa_payment


async def get_fossa_payment(
    fossa_payment_id: str,
) -> FossaPayment | None:
    return await db.fetchone(
        "SELECT * FROM fossa.fossa_payment WHERE id = :id",
        {"id": fossa_payment_id},
        FossaPayment,
    )


async def get_fossa_payments(
    fossa_ids: list[str],
) -> list[FossaPayment]:
    if len(fossa_ids) == 0:
        return []
    q = ",".join([f"'{w}'" for w in fossa_ids])
    return await db.fetchall(
        f"""
        SELECT * FROM fossa.fossa_payment WHERE fossa_id IN ({q})
        ORDER BY id
        """,
        model=FossaPayment,
    )


async def delete_atm_payment_link(atm_id: str) -> None:
    await db.execute("DELETE FROM fossa.fossa_payment WHERE id = :id", {"id": atm_id})
