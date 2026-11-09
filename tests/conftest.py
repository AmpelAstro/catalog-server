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
def uvicorn_process(pytestconfig):
    """
    Fixture that starts uvicorn in a subprocess for integration testing.
    
    Features:
    - Runs uvicorn asynchronously in background process
    - Captures stdout/stderr logs
    - Dumps logs on test failure for easier debugging
    - Automatically stops on test completion
    - Configurable host/port
    
    Usage:
        def test_api(uvicorn_process):
            url = f"http://{uvicorn_process.host}:{uvicorn_process.port}"
            # ... make requests to url
    
    Environment Variables:
        Can be overridden by setting UVICORN_HOST, UVICORN_PORT, etc.
    """
    import subprocess
    import threading
    import queue
    import sys
    import time
    import urllib.request
    import urllib.error
    
    # Only run if --integration flag is specified
    if not pytestconfig.getoption("--integration"):
        raise pytest.skip("Integration tests require --integration flag")
    
    # Check if CATALOGSERVER_URI is set (prefer external server)
    if "CATALOGSERVER_URI" in os.environ:
        raise pytest.skip(
            "CATALOGSERVER_URI is set; using external server instead of subprocess"
        )
    
    # Configuration (can be overridden by environment variables)
    host = os.environ.get("UVICORN_HOST", "127.0.0.1")
    port = int(os.environ.get("UVICORN_PORT", 8000))
    workers = int(os.environ.get("UVICORN_WORKERS", 1))
    log_level = os.environ.get("UVICORN_LOG_LEVEL", "warning")
    
    # Queue for capturing output
    output_queue = queue.Queue()
    
    # Build command
    cmd = [
        sys.executable, "-m", "uvicorn",
        "app.main:app",
        "--host", host,
        "--port", str(port),
        "--workers", str(workers),
        "--log-level", log_level,
    ]
    
    # Add environment variables for the uvicorn process
    env = os.environ.copy()
    env.update({
        "ROOT_PATH": "/api/catalogmatch",
        "PYTHONPATH": os.pathsep.join([
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            env.get("PYTHONPATH", "")
        ]),
    })
    
    # Start process
    print(f"\n{'='*80}")
    print(f"Starting uvicorn server: {' '.join(cmd)}")
    print(f"{'='*80}\n")
    
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )
    
    # Thread to capture output
    def capture_output():
        try:
            for line in proc.stdout:
                output_queue.put(line)
        except Exception as e:
            output_queue.put(f"[CAPTURE ERROR] {str(e)}")
    
    output_thread = threading.Thread(target=capture_output, daemon=True)
    output_thread.start()
    
    # Wait for server to start (up to 30 seconds)
    max_wait = float(os.environ.get("UVICORN_START_TIMEOUT", 30))
    interval = 0.5
    waited = 0
    
    url = f"http://{host}:{port}/api/catalogmatch/catalogs/"
    
    while waited < max_wait:
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    print(f"✅ Uvicorn server started successfully at {url}")
                    break
        except (urllib.error.URLError, ConnectionRefusedError, TimeoutError) as e:
            time.sleep(interval)
            waited += interval
    else:
        # Server didn't start in time
        proc.kill()
        output_thread.join(timeout=5)
        
        # Collect any output for debugging
        logs = []
        while not output_queue.empty():
            try:
                logs.append(output_queue.get_nowait())
            except queue.Empty:
                break
        
        error_msg = (
            f"❌ Uvicorn server failed to start within {max_wait}s\n"
            f"Command: {' '.join(cmd)}\n"
            f"Environment: MONGO_URI={env.get('MONGO_URI', 'not set')}, "
            f"CATSHTM_DIR={env.get('CATSHTM_DIR', 'not set')}\n"
        )
        if logs:
            error_msg += f"Logs:\n{''.join(logs)}"
        else:
            error_msg += "No logs captured"
        
        pytest.fail(error_msg)
    
    # Create wrapper class for the process
    class UvicornProcessWrapper:
        """Wrapper class for managing uvicorn subprocess."""
        
        def __init__(self, proc, output_queue, output_thread, host, port):
            self.proc = proc
            self.output_queue = output_queue
            self.output_thread = output_thread
            self.host = host
            self.port = port
            self.base_url = f"http://{host}:{port}/api/catalogmatch"
            self._logs_dumped = False
        
        def get_logs(self):
            """Get all captured logs."""
            logs = []
            while not self.output_queue.empty():
                try:
                    logs.append(self.output_queue.get_nowait())
                except queue.Empty:
                    break
            return "".join(logs)
        
        def dump_logs(self):
            """Dump logs to console."""
            if self._logs_dumped:
                return
            
            logs = self.get_logs()
            if logs:
                print("\n" + "=" * 80)
                print("UVICORN SERVER LOGS:")
                print("=" * 80)
                print(logs)
                print("=" * 80 + "\n")
                self._logs_dumped = True
        
        def stop(self):
            """Stop the uvicorn process gracefully."""
            if self.proc.poll() is None:  # Process still running
                print(f"\nStopping uvicorn server (PID: {self.proc.pid})...")
                # Try graceful shutdown first
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                    print("✅ Uvicorn server stopped gracefully")
                except subprocess.TimeoutExpired:
                    print("⚠️  Graceful shutdown timed out, force killing...")
                    # Force kill
                    self.proc.kill()
                    self.proc.wait(timeout=5)
                    print("✅ Uvicorn server killed")
            
            # Stop output thread
            if self.output_thread.is_alive():
                self.output_thread.join(timeout=5)
    
    process_wrapper = UvicornProcessWrapper(proc, output_queue, output_thread, host, port)
    
    yield process_wrapper
    
    # Teardown: dump logs and stop process
    process_wrapper.dump_logs()
    process_wrapper.stop()


@pytest.fixture(scope="session")
def web_service(pytestconfig):
    """
    Provide the base URI for integration tests.
    Uses CATALOGSERVER_URI env var if set (for CI or local development),
    otherwise starts uvicorn as a subprocess.
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
async def integration_client(request, pytestconfig):
    """
    Provides an HTTP client for integration tests.
    
    If CATALOGSERVER_URI is set, connects to that external server.
    Otherwise, starts uvicorn as a subprocess (requires --integration flag).
    """
    if "CATALOGSERVER_URI" in os.environ:
        # Use external server
        base_url = os.environ["CATALOGSERVER_URI"]
        if not base_url.endswith("/api/catalogmatch"):
            base_url = base_url.rstrip("/") + "/api/catalogmatch"
    elif pytestconfig.getoption("--integration"):
        # Use subprocess uvicorn
        uvi_proc = request.getfixturevalue("uvicorn_process")
        base_url = uvi_proc.base_url
    else:
        raise pytest.skip("integration tests require --integration flag or CATALOGSERVER_URI")
    
    # Use longer timeout for subprocess uvicorn (slower startup)
    async with AsyncClient(base_url=base_url, timeout=Timeout(30.0)) as client:
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
