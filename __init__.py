from fastapi import APIRouter

from .crud import db
from .views import fossa_generic_router
from .views_api import fossa_api_router
from .views_api_atm import fossa_api_atm_router
from .views_lnurl import fossa_lnurl_router

fossa_ext: APIRouter = APIRouter(prefix="/fossa", tags=["fossa"])
fossa_ext.include_router(fossa_generic_router)
fossa_ext.include_router(fossa_api_router)
fossa_ext.include_router(fossa_lnurl_router)
fossa_ext.include_router(fossa_api_atm_router)

fossa_static_files = [
    {
        "path": "/fossa/static",
        "name": "fossa_static",
    }
]


__all__ = [
    "db",
    "fossa_ext",
    "fossa_static_files",
]
