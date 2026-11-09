# S3 CATSHTM2 Integration Tests

This directory contains integration tests for S3-backed CATSHTM2 support via HDF5 ROS3 VFD.

## Test Structure

### Test Files

1. **`test_s3_catshtm2.py`** - Main test suite containing:
   - Unit tests for `_is_s3_uri()` helper function
   - Unit tests for local filesystem backward compatibility
   - Unit tests for S3 URI handling with ROS3 VFD
   - Mixed usage tests (local + S3)
   - Numpy array option tests
   - Offset/Block parameter tests
   - Integration tests with uvicorn server

2. **`conftest.py`** - Contains fixtures including:
   - `uvicorn_process` - **New fixture** that starts uvicorn in a subprocess
   - `web_service` - Existing fixture for external server URI
   - `integration_client` - Unified client for both modes

### Key Improvements

#### Uvicorn Subprocess Fixture (`uvicorn_process`)

The new `uvicorn_process` fixture replaces the manual uvicorn startup in GitHub Actions workflow. It:

1. **Starts uvicorn as a subprocess** - No need for separate `nohup` commands
2. **Captures all logs** - stdout and stderr are captured in a queue
3. **Dumps logs on failure** - Automatically prints logs when tests fail
4. **Auto-stops on completion** - Cleans up process after tests finish
5. **Waits for readiness** - Polls until server responds to health check
6. **Configurable** - Via environment variables (UVICORN_HOST, UVICORN_PORT, etc.)

##### Environment Variables for uvicorn_process

| Variable | Default | Description |
|----------|---------|-------------|
| `UVICORN_HOST` | `127.0.0.1` | Host to bind uvicorn to |
| `UVICORN_PORT` | `8000` | Port to listen on |
| `UVICORN_WORKERS` | `1` | Number of worker processes |
| `UVICORN_LOG_LEVEL` | `warning` | Log verbosity |
| `UVICORN_START_TIMEOUT` | `30` | Max seconds to wait for startup |

##### Usage Example

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_my_feature(integration_client):
    """Test using the uvicorn subprocess."""
    response = await integration_client.get("/some-endpoint/")
    response.raise_for_status()
    # ... assertions
```

The `integration_client` fixture automatically:
- Uses `CATALOGSERVER_URI` if set (external server)
- Falls back to `uvicorn_process` if `--integration` flag is used
- Provides a configured httpx.AsyncClient

## Running Tests

### Unit Tests (No Server Required)

```bash
# Run unit tests only (fast, no dependencies)
python -m pytest tests/test_s3_catshtm2.py -v -m "not integration"

# Run specific test classes
python -m pytest tests/test_s3_catshtm2.py::TestIsS3Uri -v
python -m pytest tests/test_s3_catshtm2.py::TestLocalPaths -v
```

### Integration Tests (Require Uvicorn)

```bash
# Run with uvicorn subprocess (automatic)
python -m pytest tests/test_s3_catshtm2.py -v --integration

# Run with external server (manual)
export CATALOGSERVER_URI=http://localhost:8000/api/catalogmatch
python -m pytest tests/test_s3_catshtm2.py -v --integration

# Run all integration tests
python -m pytest tests/ -v --integration -k "integration"
```

### With Custom Configuration

```bash
# Custom uvicorn settings
export UVICORN_HOST=0.0.0.0
export UVICORN_PORT=8080
export UVICORN_LOG_LEVEL=debug
python -m pytest tests/test_s3_catshtm2.py -v --integration
```

## Test Categories

### 1. Unit Tests (Fast, Isolated)

Tests that don't require a running server:

- `TestIsS3Uri` - URI detection logic
- `TestLocalPaths` - Local filesystem compatibility
- `TestS3Uris` - S3 URI handling (connection errors expected)
- `TestMixedUsage` - Combined local/S3 scenarios
- `TestNumpyArrayOption` - Array conversion options
- `TestOffsetBlock` - Offset/Block parameter handling

**Run:** `pytest tests/test_s3_catshtm2.py -v -m "not integration"`

### 2. Integration Tests (Require Server)

Tests that require a running uvicorn server:

- `test_uvicorn_with_s3_support` - Health check
- `test_catalogs_endpoint_with_uvicorn` - Catalog listing

**Run:** `pytest tests/test_s3_catshtm2.py -v --integration`

## GitHub Actions Workflow Update

The new fixtures allow simplifying the GitHub Actions workflow. Instead of manually starting uvicorn with `nohup`, you can now use:

```yaml
steps:
  - name: Test with pytest
    run: |
      poetry run pytest tests --integration
    env:
      MONGO_URI: mongodb://root:12345@localhost:27017
      CATSHTM_DIR: ${{ github.workspace }}/src/tests/test-data/catsHTM2
```

The `uvicorn_process` fixture will automatically:
1. Start uvicorn with the correct configuration
2. Wait for the server to be ready
3. Capture all logs
4. Dump logs on failure
5. Stop the server when tests complete

### Benefits Over Old Approach

| Aspect | Old Approach | New Approach |
|--------|-------------|--------------|
| Process Management | Manual `nohup` + PID tracking | Automatic via fixture |
| Log Collection | Manual `cat uvicorn.log` | Automatic capture + dump |
| Failure Debugging | Manual log inspection | Automatic log dump on failure |
| Cleanup | Manual `kill $PID` | Automatic in teardown |
| Readiness Check | Manual `sleep` + `curl` | Automatic polling |
| Flexibility | Hardcoded in workflow | Configurable via env vars |

## Debugging Tips

### View Uvicorn Logs

When tests fail, the uvicorn logs are automatically dumped to the console. You can also access them programmatically:

```python
def test_debug(uvicorn_process):
    # Get logs at any point
    logs = uvicorn_process.get_logs()
    print("=== LOGS ===")
    print(logs)
    print("=== END ===")
```

### Increase Timeout

If your server takes longer to start:

```bash
export UVICORN_START_TIMEOUT=60
python -m pytest tests/test_s3_catshtm2.py -v --integration
```

### Enable Debug Logging

```bash
export UVICORN_LOG_LEVEL=debug
python -m pytest tests/test_s3_catshtm2.py -v --integration
```

## Test Data Requirements

Some tests require test data to be present:

1. **MongoDB Data** - For extcats catalogs
   - Location: `tests/test-data/minimongodumps/`
   - Contains: TNS and milliquas test data

2. **CATSHTM2 Data** - For local HDF5 files
   - Location: `tests/test-data/catsHTM2/`
   - Set via: `CATSHTM_DIR` environment variable

3. **S3 Test Data** - For future S3 integration
   - Currently: Tests expect server at `localhost:7070`
   - Configure via: `AWS_ENDPOINT_URL` environment variable

## Contributing New Tests

When adding new integration tests:

1. **Use `integration_client` fixture** for HTTP clients:
   ```python
   async def test_new_feature(integration_client):
       response = await integration_client.get("/new-endpoint/")
       # ...
   ```

2. **Mark with `@pytest.mark.integration`**:
   ```python
   @pytest.mark.integration
   async def test_new_feature(integration_client):
       # ...
   ```

3. **Handle missing dependencies gracefully**:
   ```python
   try:
       from catsHTM.catsHTM.class_HDF5 import HDF5
   except ImportError:
       pytest.skip("catsHTM module not available")
   ```

## Known Limitations

1. **Vendor Module Resolution** - PyRight may complain about unresolved imports from `catsHTM`. This is expected and doesn't affect runtime.

2. **External Server Priority** - If `CATALOGSERVER_URI` is set, the `uvicorn_process` fixture is skipped. This prevents conflicts.

3. **Single Worker** - By default, uvicorn runs with 1 worker. Increase `UVICORN_WORKERS` if needed.

4. **Port Binding** - The default port is 8000. Change `UVICORN_PORT` if this conflicts with other services.

## Migration Guide

If you have existing tests that manually manage uvicorn:

### Before (Manual Management)

```yaml
# GitHub Actions
- name: Start uvicorn server
  run: |
    nohup poetry run uvicorn app.main:app --host 0.0.0.0 --port 8000 > uvicorn.log 2>&1 &
    UVICORN_PID=$!
    echo "UVICORN_PID=$UVICORN_PID" >> $GITHUB_ENV
    sleep 5
    curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/catalogmatch/
- name: Test with pytest
  run: poetry run pytest tests --integration
- name: Dump uvicorn logs on failure
  if: failure()
  run: cat uvicorn.log || true
- name: Stop uvicorn server
  if: always()
  run: kill ${UVICORN_PID} || true
```

### After (Automatic Fixture)

```yaml
# GitHub Actions
- name: Test with pytest
  run: poetry run pytest tests --integration
  env:
    MONGO_URI: mongodb://root:12345@localhost:27017
    CATSHTM_DIR: ${{ github.workspace }}/src/tests/test-data/catsHTM2
```

Much simpler!

## References

- [Main Implementation Plan](../IMPLEMENTATION_PLAN_S3_CATSHTM2.md)
- [Technical Findings](../S3_IMPLEMENTATION_FINDINGS.md)
- [Cheat Sheet](../CHEAT_SHEET_S3_CATSHTM2.md)
- [Modified class_HDF5.py](../../vendor/github.com/AmpelAstro/catsHTM/catsHTM/class_HDF5.py)
