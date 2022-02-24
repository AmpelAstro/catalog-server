import json
import subprocess
import time
import os
from pathlib import Path

import mongomock
import pytest
from bson import decode_all
from httpx import AsyncClient

from app.main import app
from app.mongo import get_catq
from app.settings import Settings


def pytest_addoption(parser):
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="run docker-based integration tests",
    )


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
def catshtm_dir(monkeypatch):
    settings = Settings(catshtm_dir=Path(__file__).parent / "test-data" / "catsHTM2")
    monkeypatch.setattr(
        "app.cone_search.settings",
        settings,
    )
    monkeypatch.setattr(
        "app.catalogs.settings",
        settings,
    )
    monkeypatch.setattr(
        "app.models.settings",
        settings,
    )
    


@pytest.fixture
async def mock_client(mock_extcats, catshtm_dir, without_keys_doc):
    async with AsyncClient(app=app, base_url="http://test", follow_redirects=True) as client:
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


@pytest.fixture
async def integration_client(local_mongo, catshtm_dir):
    async with AsyncClient(app=app, base_url="http://test", follow_redirects=True) as client:
        yield client


# metafixture as suggested in https://github.com/pytest-dev/pytest/issues/349#issuecomment-189370273
@pytest.fixture(params=["mock_client", "integration_client"])
def test_client(request):
    yield request.getfixturevalue(request.param)
