from typing import Optional

import shortuuid
from lnbits.db import Database
from lnbits.helpers import urlsafe_short_hash

from .models import CreateFossa, CreateFossaPayment, Fossa, FossaPayment

db = Database("ext_fossa")


async def create_fossa(data: CreateFossa) -> Fossa:
    fossa_id = shortuuid.uuid()[:5]
    fossa_key = urlsafe_short_hash()
    device = Fossa(
        id=fossa_id,
        key=fossa_key,
        title=data.title,
        wallet=data.wallet,
        profit=data.profit,
        currency=data.currency,
        boltz=data.boltz,
    )
    await db.insert("fossa.fossa", device)
    return device


async def update_fossa(fossa: Fossa) -> Fossa:
    await db.update("fossa.fossa", fossa)
    return fossa


async def get_fossa(fossa_id: str) -> Optional[Fossa]:
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


async def create_fossa_payment(
    deviceid: str,
    payload: str,
    pin: int,
    payhash: str,
    sats: int = 0,
) -> CreateFossaPayment:
    fossa_payment_id = urlsafe_short_hash()
    payment = CreateFossaPayment(
        id=fossa_payment_id,
        deviceid=deviceid,
        payload=payload,
        pin=pin,
        payhash=payhash,
        sats=sats,
    )
    await db.insert("fossa.fossa_payment", payment)
    return payment


async def update_fossa_payment(
    fossa_payment: CreateFossaPayment,
) -> CreateFossaPayment:
    await db.update("fossa.fossa_payment", fossa_payment)
    return fossa_payment


async def get_fossa_payment(
    fossa_payment_id: str,
) -> Optional[FossaPayment]:
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
        SELECT * FROM fossa.fossa_payment WHERE deviceid IN ({q})
        ORDER BY id
        """,
        model=FossaPayment,
    )


async def get_fossa_payment_by_payhash(
    payhash: str,
) -> Optional[FossaPayment]:
    return await db.fetchone(
        "SELECT * FROM fossa.fossa_payment WHERE payhash = :payhash",
        {"payhash": payhash},
        FossaPayment,
    )


async def get_fossa_payment_by_payload(
    payload: str,
) -> Optional[FossaPayment]:
    return await db.fetchone(
        "SELECT * FROM fossa.fossa_payment WHERE payload = :payload",
        {"payload": payload},
        FossaPayment,
    )


async def get_recent_fossa_payment(payload: str) -> Optional[FossaPayment]:
    return await db.fetchone(
        """
        SELECT * FROM fossa.fossa_payment
        WHERE payload = :payload ORDER BY timestamp DESC LIMIT 1
        """,
        {"payload": payload},
        FossaPayment,
    )


async def delete_atm_payment_link(atm_id: str) -> None:
    await db.execute("DELETE FROM fossa.fossa_payment WHERE id = :id", {"id": atm_id})
