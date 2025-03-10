import json
from datetime import datetime, timezone
from typing import Optional

from lnurl.types import LnurlPayMetadata
from pydantic import BaseModel, Field


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


class FossaPayment(BaseModel):
    id: str
    fossa_id: str
    payment_hash: Optional[str] = None
    payload: str
    pin: int
    sats: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
