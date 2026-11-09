from ipaddress import ip_address
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from lnbits.core.services import lnurl as core_lnurl
from lnbits.settings import settings
from starlette.exceptions import HTTPException

from .. import views_api_atm as views


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("payment_request", ["alice@pay.example", "lnurl1example"])
async def test_lnurl_invoice_uses_core_and_preserves_amount(
    monkeypatch, payment_request
):
    assert views.get_pr_from_lnurl is core_lnurl.get_pr_from_lnurl
    fetch = AsyncMock(return_value="lnbc1invoice")
    monkeypatch.setattr(views, "get_pr_from_lnurl", fetch)
    monkeypatch.setattr(
        views.bolt11,
        "decode",
        lambda pr: SimpleNamespace(payment_hash="hash", amount_msat=21000),
    )
    assert (
        await views._validate_payment_request(payment_request, 21000) == "lnbc1invoice"
    )
    fetch.assert_awaited_once_with(payment_request, 21000)


@pytest.mark.anyio
async def test_direct_invoice_keeps_amount_validation(monkeypatch):
    fetch = AsyncMock()
    monkeypatch.setattr(views, "get_pr_from_lnurl", fetch)
    monkeypatch.setattr(
        views.bolt11,
        "decode",
        lambda pr: SimpleNamespace(payment_hash="hash", amount_msat=21000),
    )
    assert (
        await views._validate_payment_request("lnbc1invoice", 21000) == "lnbc1invoice"
    )
    with pytest.raises(HTTPException, match="withdraw amount"):
        await views._validate_payment_request("lnbc1invoice", 22000)
    fetch.assert_not_awaited()


@pytest.mark.anyio
async def test_private_lnurl_fails_before_payment(monkeypatch):
    monkeypatch.setattr(settings, "lnbits_callback_url_rules", [])
    monkeypatch.setattr(settings, "lnbits_lnurl_allow_private_ips", False)
    monkeypatch.setattr(
        core_lnurl,
        "_resolve_lnurl_host",
        AsyncMock(return_value=[ip_address("127.0.0.1")]),
    )
    send = AsyncMock()
    monkeypatch.setattr(core_lnurl, "_send_lnurl_request", send)
    pay = AsyncMock()
    monkeypatch.setattr(views, "pay_invoice", pay)
    with pytest.raises(HTTPException) as exc:
        await views._validate_payment_request("alice@pay.example", 21000)
    assert exc.value.status_code == 403
    send.assert_not_awaited()
    pay.assert_not_awaited()


@pytest.mark.anyio
async def test_public_metadata_cannot_point_at_private_callback(monkeypatch):
    import json

    monkeypatch.setattr(settings, "lnbits_callback_url_rules", [])
    monkeypatch.setattr(settings, "lnbits_lnurl_allow_private_ips", False)
    resolve = AsyncMock(
        side_effect=[[ip_address("93.184.216.34")], [ip_address("127.0.0.1")]]
    )
    monkeypatch.setattr(core_lnurl, "_resolve_lnurl_host", resolve)
    metadata = {
        "tag": "payRequest",
        "callback": "https://internal.example/invoice",
        "minSendable": 1000,
        "maxSendable": 100000,
        "metadata": '[["text/plain","Payment"]]',
    }
    send = AsyncMock(return_value=(200, {}, json.dumps(metadata).encode()))
    monkeypatch.setattr(core_lnurl, "_send_lnurl_request", send)
    with pytest.raises(HTTPException) as exc:
        await views._validate_payment_request("alice@pay.example", 21000)
    assert exc.value.status_code == 403
    assert resolve.await_count == 2
    assert send.await_count == 1  # The private callback is never requested.
