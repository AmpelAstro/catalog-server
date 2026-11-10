import logging
from functools import lru_cache

from extcats.CatalogQuery import CatalogQuery
from pymongo import MongoClient

from .settings import settings

log = logging.getLogger(__name__)
mongo_db: MongoClient = MongoClient(str(settings.mongo_uri))


def get_mongo() -> MongoClient:
    return mongo_db


@lru_cache(maxsize=128)
def get_catq(name: str) -> CatalogQuery | None:
    try:
        return CatalogQuery(name, dbclient=get_mongo())
    except KeyError:
        log.exception(f"{name} is not a valid extcats catalog")
        return None
