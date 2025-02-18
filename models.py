import json
from datetime import datetime

from lnurl.types import LnurlPayMetadata
from pydantic import BaseModel


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


class CreateFossaPayment(BaseModel):
    id: str
    deviceid: str
    payhash: str
    payload: str
    pin: int
    sats: int


class FossaPayment(BaseModel):
    id: str
    deviceid: str
    payhash: str
    payload: str
    pin: int
    sats: int
    timestamp: datetime


class Lnurlencode(BaseModel):
    url: str
