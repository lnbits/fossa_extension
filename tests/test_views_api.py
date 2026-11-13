from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from lnbits.core.models import KeyType, Wallet, WalletTypeInfo
from lnbits.decorators import require_admin_key

from .. import crud, views_api
from ..models import Fossa


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,current_wallet,target_wallet,status",
    [
        ("POST", "own", "own", 200),
        ("POST", "own", "second", 200),
        ("POST", "own", "other", 403),
        ("POST", "own", "missing", 404),
        ("PUT", "own", "own", 200),
        ("PUT", "own", "second", 200),
        ("PUT", "own", "other", 403),
        ("PUT", "own", "missing", 404),
        ("PUT", "other", "own", 403),
    ],
)
async def test_wallet_selection(
    monkeypatch, method, current_wallet, target_wallet, status
):
    wallets = {
        wallet_id: Wallet(
            id=wallet_id,
            user=user,
            name=wallet_id,
            adminkey=f"{wallet_id}-admin",
            inkey=f"{wallet_id}-invoice",
        )
        for wallet_id, user in [
            ("own", "user"),
            ("second", "user"),
            ("other", "other-user"),
        ]
    }
    fossa = Fossa(
        id="device",
        key="existing-key",
        title="Original",
        wallet=current_wallet,
        currency="sat",
        profit=0,
        boltz=False,
    )
    original = fossa.model_dump()
    monkeypatch.setattr(views_api, "get_wallet", AsyncMock(side_effect=wallets.get))
    monkeypatch.setattr(views_api, "get_fossa", AsyncMock(return_value=fossa))
    insert = AsyncMock()
    update = AsyncMock()
    monkeypatch.setattr(crud.db, "insert", insert)
    monkeypatch.setattr(crud.db, "update", update)

    app = FastAPI()
    app.include_router(views_api.fossa_api_router, prefix="/fossa")
    app.dependency_overrides[require_admin_key] = lambda: WalletTypeInfo(
        KeyType.admin, wallets["own"]
    )
    path = "/fossa/api/v1/fossa"
    if method == "PUT":
        path += f"/{fossa.id}"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(
            method,
            path,
            json={
                "title": "Changed",
                "wallet": target_wallet,
                "currency": "sat",
                "profit": 0,
            },
        )

    assert response.status_code == status
    if status != 200:
        insert.assert_not_awaited()
        update.assert_not_awaited()
        assert fossa.model_dump() == original
        assert "key" not in response.json()
    elif method == "POST":
        insert.assert_awaited_once()
        update.assert_not_awaited()
        assert insert.call_args.args[1].wallet == target_wallet
        assert response.json()["wallet"] == target_wallet
        assert response.json()["key"]
    else:
        insert.assert_not_awaited()
        update.assert_awaited_once_with("fossa.fossa", fossa)
        assert fossa.wallet == target_wallet
        assert response.json()["wallet"] == target_wallet
        assert response.json()["key"] == original["key"]
