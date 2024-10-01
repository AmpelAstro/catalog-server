import asyncio
import json
import subprocess
import time
import os
from pathlib import Path

import mongomock
import pytest
import pytest_asyncio
from bson import decode_all
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.mongo import get_catq
from app.settings import Settings, settings

import nest_asyncio
nest_asyncio.apply()

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
    Bring up an instance of the service in Nginx Unit, using docker-compose
    """
    if not pytestconfig.getoption("--integration"):
        raise pytest.skip("integration tests require --integration flag")
    # use an external fixture for local development
    if "CATALOGSERVER_URI" in os.environ:
        yield os.environ["CATALOGSERVER_URI"]
        return
    basedir = Path(__file__).parent.parent
    try:
        subprocess.check_call(
            ["docker-compose", "up", "-d", "--force-recreate"],
            cwd=basedir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        raise pytest.skip("integration test requires docker-compose")
    try:
        # wait for Unit emit the provided configuration over the control socket,
        # indicating that it has restarted and is ready to accept requests
        web = subprocess.check_output(["docker-compose", "ps", "-q", "web"]).strip().decode()
        delay = 0.1
        for _ in range(10):
            try:
                config = json.loads(
                    subprocess.check_output(
                        [
                            "docker",
                            "exec",
                            web,
                            "curl",
                            "--unix-socket",
                            "/run/control.unit.sock",
                            "http://localhost/",
                        ]
                    )
                )
                if "catalogmatch" in config.get("config", {}).get("applications", {}):
                    break
            except subprocess.CalledProcessError:
                ...
            time.sleep(delay)
            delay *= 2
        else:
            subprocess.call(['docker', 'logs', web])
            raise RuntimeError(f"Application server ({web}) failed to start")
        # find the external mapping for port 80
        port = (
            subprocess.check_output(["docker-compose", "port", "web", "80"])
            .strip()
            .decode()
            .split(":")[1]
        )
        yield f"http://localhost:{port}"
    finally:
        subprocess.check_call(
            ["docker-compose", "down"],
            cwd=basedir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

@pytest_asyncio.fixture
async def integration_client(web_service):
    async with AsyncClient(base_url=web_service+"/api/catalogmatch") as client:
        yield client


# metafixture as suggested in https://github.com/pytest-dev/pytest/issues/349#issuecomment-189370273
@pytest_asyncio.fixture(params=["mock_client", "integration_client"])
async def test_client(request):
    yield request.getfixturevalue(request.param)
