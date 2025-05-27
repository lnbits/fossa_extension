import json
from datetime import datetime, timezone
from typing import Optional

from lnbits.utils.exchange_rates import fiat_amount_as_satoshis
from lnurl.types import LnurlPayMetadata
from pydantic import BaseModel, Field


class LnurlDecrypted(BaseModel):
    pin: int
    amount: float


class LnurlPayload(BaseModel):
    fossa_id: str
    payload: str


class CreateFossa(BaseModel):
    title: str
    wallet: str
    currency: str
    profit: float
    boltz: bool = False


class Fossa(BaseModel):
    id: str
    key: str
    title: str
    wallet: str
    profit: float
    currency: str
    boltz: bool

    @property
    def lnurlpay_metadata(self) -> LnurlPayMetadata:
        return LnurlPayMetadata(json.dumps([["text/plain", self.title]]))

    async def amount_to_sats(self, amount: float) -> int:
        sats = (
            int(amount)
            if self.currency == "sat"
            else await fiat_amount_as_satoshis(float(amount) / 100, self.currency)
        )
        if self.profit <= 0:
            return sats
        return int(sats - ((sats / 100) * self.profit))


class FossaPayment(BaseModel):
    id: str
    fossa_id: str
    payment_hash: Optional[str] = None
    payload: str
    pin: int
    sats: int
    amount: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
