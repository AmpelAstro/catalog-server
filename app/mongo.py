import logging
from functools import lru_cache
from typing import Annotated

import pymongo
from extcats.CatalogQuery import CatalogQuery
from fastapi import Depends

from .settings import settings

log = logging.getLogger(__name__)
mongo_db: pymongo.MongoClient = pymongo.MongoClient(str(settings.mongo_uri))


def get_mongo() -> pymongo.MongoClient:
    return mongo_db

MongoClient = Annotated[pymongo.MongoClient, Depends(get_mongo)]


@lru_cache(maxsize=128)
def get_catq(name: str) -> CatalogQuery | None:
    try:
        return CatalogQuery(name, dbclient=get_mongo())
    except KeyError:
        log.exception(f"{name} is not a valid extcats catalog")
        return None
