from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from lnbits.decorators import require_admin_key

from .. import views, views_api, views_api_atm
from ..models import ONCHAIN_UNAVAILABLE_MESSAGE, Fossa


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def fossa():
    # A previously enabled record must not allow new swaps.
    return Fossa(
        id="legacy",
        key="test",
        title="Test",
        wallet="wallet",
        profit=0,
        currency="sat",
        boltz=True,
    )


@pytest.fixture
def app(monkeypatch, fossa):
    app = FastAPI()
    app.include_router(views_api.fossa_api_router, prefix="/fossa")
    app.include_router(views_api_atm.fossa_api_atm_router, prefix="/fossa")
    app.include_router(views.fossa_generic_router, prefix="/fossa")
    app.dependency_overrides[require_admin_key] = lambda: SimpleNamespace(
        wallet=SimpleNamespace(id="wallet", user="owner")
    )
    monkeypatch.setattr(views_api, "get_fossa", AsyncMock(return_value=fossa))
    monkeypatch.setattr(
        views_api, "get_wallet", AsyncMock(return_value=SimpleNamespace(user="owner"))
    )
    return app


@pytest.mark.anyio
@pytest.mark.parametrize("method,path", [("POST", ""), ("PUT", "/legacy")])
@pytest.mark.parametrize("enabled", [True, 1, "true", "yes", "on"])
async def test_api_rejects_enabling_swaps(app, monkeypatch, method, path, enabled):
    create = AsyncMock()
    update = AsyncMock()
    monkeypatch.setattr(views_api, "create_fossa", create)
    monkeypatch.setattr(views_api, "update_fossa", update)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.request(
            method,
            f"/fossa/api/v1/fossa{path}",
            json={
                "title": "Test",
                "wallet": "wallet",
                "currency": "sat",
                "profit": 0,
                "boltz": enabled,
            },
        )
    assert response.status_code == 422
    assert ONCHAIN_UNAVAILABLE_MESSAGE in response.text
    create.assert_not_awaited()
    update.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("method,path", [("POST", ""), ("PUT", "/legacy")])
@pytest.mark.parametrize("fields", [{}, {"boltz": False}])
async def test_lightning_configuration_still_saves(
    app, monkeypatch, method, path, fields
):
    async def create(data):
        return Fossa(id="new", key="test", **data.model_dump())

    async def update(data):
        return data

    monkeypatch.setattr(views_api, "create_fossa", create)
    monkeypatch.setattr(views_api, "update_fossa", update)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.request(
            method,
            f"/fossa/api/v1/fossa{path}",
            json={
                "title": "Updated",
                "wallet": "wallet",
                "currency": "sat",
                "profit": 0,
                **fields,
            },
        )
    assert response.status_code == 200
    assert response.json()["boltz"] is False
    assert response.json()["title"] == "Updated"


@pytest.mark.anyio
@pytest.mark.parametrize("asset", ["BTCtempBTC", "L-BTCtempBTC", "anything"])
async def test_swap_route_is_closed_before_side_effects(app, monkeypatch, asset):
    reads = AsyncMock(side_effect=AssertionError("Must reject before database access"))
    pay = AsyncMock()
    update = AsyncMock()
    parse = Mock(side_effect=AssertionError("Must reject before payload processing"))
    monkeypatch.setattr(views_api_atm, "get_fossa", reads)
    monkeypatch.setattr(views_api_atm, "pay_invoice", pay)
    monkeypatch.setattr(views_api_atm, "update_fossa_payment", update)
    monkeypatch.setattr(views_api_atm, "parse_lnurl_payload", parse)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.get(f"/fossa/api/v1/boltz/test/{asset}/test-address")
    assert response.status_code == 410
    assert response.json()["detail"] == ONCHAIN_UNAVAILABLE_MESSAGE
    reads.assert_not_awaited()
    pay.assert_not_awaited()
    update.assert_not_awaited()
    parse.assert_not_called()


@pytest.mark.anyio
async def test_legacy_enabled_record_has_no_onchain_atm_options(
    app, monkeypatch, fossa
):
    monkeypatch.setattr(views, "get_fossa", AsyncMock(return_value=fossa))
    monkeypatch.setattr(views, "get_wallet", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(views, "get_fossa_payment", AsyncMock(return_value=None))
    monkeypatch.setattr(
        views,
        "parse_lnurl_payload",
        lambda _: SimpleNamespace(fossa_id=fossa.id, payload="test"),
    )
    monkeypatch.setattr(
        views,
        "aes_decrypt_payload",
        lambda *_: SimpleNamespace(amount=100),
    )
    monkeypatch.setattr(
        views,
        "fossa_renderer",
        lambda: SimpleNamespace(
            TemplateResponse=lambda name, context: JSONResponse(
                {k: v for k, v in context.items() if k != "request"}
            )
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.get("/fossa/atm", params={"lightning": "test"})
    assert response.status_code == 200
    assert response.json()["boltz"] is False
    assert response.json()["amount_sat"] == 100
