import json
from datetime import datetime, timezone

from lnbits.utils.exchange_rates import fiat_amount_as_satoshis
from lnurl.types import LnurlPayMetadata
from pydantic import BaseModel, Field, field_validator

ONCHAIN_UNAVAILABLE_MESSAGE = (
    "On-chain and Liquid payouts are unavailable until a replacement provider is added."
)


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

    @field_validator("boltz")
    @classmethod
    def reject_onchain_support(cls, value: bool) -> bool:
        if value:
            raise ValueError(ONCHAIN_UNAVAILABLE_MESSAGE)
        return value


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
    payment_hash: str | None = None
    payload: str
    pin: int
    sats: int
    amount: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
