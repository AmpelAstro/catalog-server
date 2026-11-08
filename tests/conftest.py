import json
import subprocess
import time
import os
from pathlib import Path

import mongomock
import pytest
import pytest_asyncio
from bson import decode_all
from httpx import AsyncClient, ASGITransport, Timeout

from app.main import app
from app.mongo import get_catq
from app.settings import Settings, settings

import nest_asyncio
nest_asyncio.apply()

def pytest_addoption(parser):
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="run docker-based integration tests",
    )

# # https://github.com/encode/starlette/issues/652#issuecomment-569327566
# @pytest.mark.anyio
# @pytest_asyncio.fixture(scope='module')
# def event_loop():
#     loop = asyncio.get_event_loop_policy().new_event_loop()
#     asyncio.set_event_loop(loop)
#     yield loop
#     # assert loop.is_running()


@pytest.fixture(scope="session")
def mock_mongoclient():
    test_data_dir = Path(__file__).parent / "test-data"
    mc = mongomock.MongoClient()
    # read catalogs from test-data, adding key metadata
    # - milliquas happens to have both geoJSON and healpix indexes, and will
    #   default to healpix, which works with mongomock
    # - TNS has a geoJSON index only
    for catalog, count in (("TNS", 12), ("milliquas", 10)):
        db = mc.get_database(catalog)
        with open(test_data_dir / "minimongodumps" / catalog / "meta.bson", "rb") as f:
            db.get_collection("meta").insert_many(decode_all(f.read()))
        with open(test_data_dir / "minimongodumps" / catalog / "srcs.bson", "rb") as f:
            db.get_collection("srcs").insert_many(decode_all(f.read()))
        assert db.get_collection("srcs").count_documents({}) == count
    return mc


@pytest.fixture
def mock_extcats(monkeypatch, mock_mongoclient):
    monkeypatch.setattr("app.mongo.mongo_db", mock_mongoclient)
    get_catq.cache_clear()


@pytest.fixture
def local_mongo(monkeypatch):
    from pymongo import MongoClient

    if "MONGO_URI" in os.environ:
        monkeypatch.setattr("app.mongo.mongo_db", MongoClient(os.environ["MONGO_URI"]))
        get_catq.cache_clear()
        yield
        get_catq.cache_clear()
    else:
        pytest.skip("No local MongoDB")


@pytest.fixture
def without_keys_doc(mock_mongoclient):
    meta = mock_mongoclient.get_database("milliquas").get_collection("meta")
    doc = meta.find_one_and_delete({"_id": "keys"})
    get_catq.cache_clear()
    yield
    meta.insert_one(doc)


@pytest.fixture
def mock_catshtm(monkeypatch):
    original_settings = settings.model_copy()
    monkeypatch.setenv("CATSHTM_DIR", str(Path(__file__).parent / "test-data" / "catsHTM2"))
    try:
        settings.__dict__.update(Settings().__dict__)
        yield
    finally:
        settings.__dict__.update(original_settings.__dict__)
    

@pytest_asyncio.fixture
async def mock_client(mock_extcats, mock_catshtm, without_keys_doc):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture(scope="session")
def web_service(pytestconfig):
    """
    Provide the base URI for integration tests.
    Uses CATALOGSERVER_URI env var if set (for CI or local development),
    otherwise skips integration tests.
    """
    if not pytestconfig.getoption("--integration"):
        raise pytest.skip("integration tests require --integration flag")
    
    # use an external fixture for local development or CI
    if "CATALOGSERVER_URI" in os.environ:
        uri = os.environ["CATALOGSERVER_URI"]
        # Ensure the URI ends with /api/catalogmatch for consistency
        if not uri.endswith("/api/catalogmatch"):
            uri = uri.rstrip("/") + "/api/catalogmatch"
        yield uri
        return
    
    # Fallback: try to detect if we're in CI with uvicorn running
    # This allows the test suite to work with the GitHub Actions workflow
    # which starts uvicorn separately
    raise pytest.skip("integration tests require CATALOGSERVER_URI env var or docker-compose")

@pytest_asyncio.fixture
async def integration_client(web_service):
    # Shorter timeout for faster feedback
    async with AsyncClient(base_url=web_service, timeout=Timeout(5.0)) as client:
        yield client


@pytest.fixture
def test_client(request, pytestconfig):
    """
    Provides the appropriate client based on test mode.
    - Without --integration: uses mock_client (in-process, mocked DB)
    - With --integration: uses integration_client (external server, real DB)
    """
    if pytestconfig.getoption("--integration"):
        return request.getfixturevalue("integration_client")
    else:
        return request.getfixturevalue("mock_client")
