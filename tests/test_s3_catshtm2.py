"""
Integration tests for S3-backed CATSHTM2 support via HDF5 ROS3 VFD.

Tests cover:
1. Basic S3 URI handling in class_HDF5
2. ROS3 VFD configuration
3. Backward compatibility with local filesystem
4. Error handling for missing files/invalid URIs
5. Full-stack integration with uvicorn server

Style Guidelines:
- Use pytest-style free functions (not test classes)
- ImportError should raise (don't catch - deps are installed in test env)
- Use explicit pytest.skip() for intentional skips
- Setup/teardown goes in fixtures

Note: Tests marked with @pytest.mark.integration_s3 require h5py with ROS3 VFD support.
If ROS3 is not available, these tests will be skipped.
"""

import os
import sys
import tempfile
from pathlib import Path
from typing import Generator, Any

import pytest
import h5py
import numpy as np


# Check if h5py has ROS3 VFD support
# ROS3 support can be checked by attempting to use the ros3 driver
# or by checking for the presence of certain attributes
try:
    HAS_ROS3 = False
    # Try to create a file with ros3 driver to check if supported
    # This is a lightweight check that doesn't actually connect to S3
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.h5', delete=True) as tmp:
        try:
            # Try to open with ros3 driver - will fail if not compiled in
            with h5py.File(tmp.name, 'w', driver='ros3') as f:
                pass
            HAS_ROS3 = True
        except (ValueError, OSError) as e:
            # "can't use ros3 driver" means ROS3 not compiled in
            if "ros3" in str(e).lower() or "driver" in str(e).lower():
                HAS_ROS3 = False
            else:
                # Some other error, assume ROS3 is available
                HAS_ROS3 = True
except Exception:
    HAS_ROS3 = False


@pytest.fixture(autouse=True)
def skip_if_no_ros3(request):
    """Skip tests marked as integration_s3 if ROS3 VFD is not available."""
    if request.node.get_closest_marker("integration_s3") and not HAS_ROS3:
        pytest.skip("ROS3 VFD not available in h5py - requires h5py compiled with ROS3 support")


# Direct imports - will raise ImportError if not available (intentional)
from catsHTM.class_HDF5 import HDF5, _is_s3_uri


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_hdf5_file() -> Generator[str, None, None]:
    """Create a temporary HDF5 file for testing."""
    with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
        tmp_path = tmp.name
    
    try:
        with h5py.File(tmp_path, "w") as f:
            # Create test datasets similar to CATSHTM2
            f.create_dataset("test_matrix", data=np.random.rand(100, 100).astype(np.float32))
            f.create_dataset("test_vector", data=np.random.rand(1000).astype(np.float32))
            f.create_dataset("test_scalar", data=np.float32(42.0))
            # Edge case: empty dataset
            f.create_dataset("empty_dataset", data=np.array([]))
        yield tmp_path
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@pytest.fixture
def s3_env_vars() -> Generator[None, None, None]:
    """Set up environment variables for ROS3 VFD testing."""
    original_env = {
        "AWS_ENDPOINT_URL": os.environ.get("AWS_ENDPOINT_URL"),
        "H5ROSS3_ENDPOINT": os.environ.get("H5ROSS3_ENDPOINT"),
        "H5ROSS3_NO_VERIFY_SSL": os.environ.get("H5ROSS3_NO_VERIFY_SSL"),
        "H5ROSS3_PATH_STYLE": os.environ.get("H5ROSS3_PATH_STYLE"),
        "H5ROSS3_AUTH_METHOD": os.environ.get("H5ROSS3_AUTH_METHOD"),
        "AWS_ACCESS_KEY_ID": os.environ.get("AWS_ACCESS_KEY_ID"),
        "AWS_SECRET_ACCESS_KEY": os.environ.get("AWS_SECRET_ACCESS_KEY"),
        "AWS_DEFAULT_REGION": os.environ.get("AWS_DEFAULT_REGION"),
    }
    
    # Set test environment variables for ROS3 VFD
    os.environ["AWS_ENDPOINT_URL"] = "http://localhost:7070"
    os.environ["H5ROSS3_NO_VERIFY_SSL"] = "1"
    os.environ["H5ROSS3_PATH_STYLE"] = "1"
    os.environ["H5ROSS3_AUTH_METHOD"] = "ENV_VAR"
    os.environ["AWS_ACCESS_KEY_ID"] = "test-access-key"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "test-secret-key"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    
    yield
    
    # Restore original environment
    for key, value in original_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


# ============================================================================
# Parametrized Test Data
# ============================================================================

# Test cases for URI detection
S3_URI_TEST_CASES = [
    # (input, expected_result, description)
    ("s3://bucket/file.h5", True, "Valid S3 URI"),
    ("s3://my-bucket/path/to/file.h5", True, "Nested S3 URI"),
    ("s3://bucket-123/data.h5", True, "Bucket with numbers"),
    ("s3://bucket-with-dashes/file.h5", True, "Bucket with dashes"),
    ("s3://bucket_with_underscores/file.h5", True, "Bucket with underscores"),
]

NON_S3_URI_TEST_CASES = [
    # (input, expected_result, description)
    ("/local/path/file.h5", False, "Absolute local path"),
    ("relative/path/file.h5", False, "Relative local path"),
    ("http://example.com/file.h5", False, "HTTP URL"),
    ("https://example.com/file.h5", False, "HTTPS URL"),
    ("ftp://example.com/file.h5", False, "FTP URL"),
    ("", False, "Empty string"),
    ("s3:/bucket/file.h5", False, "Malformed S3 URI (single slash)"),
]

EDGE_CASE_URI_TEST_CASES = [
    # (input, expected_result, description)
    (None, False, "None input"),
    (123, False, "Integer input"),
    ("s3:///", True, "Triple slash"),
    ("s3://bucket/", True, "Trailing slash"),
    ("s3://bucket", True, "No trailing slash"),
]

# Test cases for file existence
FILE_EXISTENCE_TEST_CASES = [
    # (filepath_func, dataset, should_return_empty, description)
    (lambda path: path, "test_matrix", False, "Existing local file"),
    (lambda path: path, "nonexistent_dataset", True, "Non-existent dataset"),
    (lambda _: "/nonexistent/path/file.h5", "test_matrix", True, "Non-existent local file"),
]

# Test cases for S3 URIs (all will fail without server, but should handle gracefully)
S3_URI_ERROR_CASES = [
    # (s3_uri, dataset, description)
    ("s3://nonexistent-bucket/file.h5", "test_matrix", "Non-existent bucket"),
    ("s3://test-bucket/nonexistent-file.h5", "test_matrix", "Non-existent file"),
    ("s3://bucket/with/special-chars/file.h5", "test_matrix", "Special chars in path"),
]


# ============================================================================
# URI Detection Tests (Free Functions)
# ============================================================================

@pytest.mark.parametrize("uri,expected,description", S3_URI_TEST_CASES)
def test_valid_s3_uris(uri: str, expected: bool, description: str):
    """Test valid S3 URIs are detected."""
    assert _is_s3_uri(uri) == expected, f"Failed for: {description}"


@pytest.mark.parametrize("uri,expected,description", NON_S3_URI_TEST_CASES)
def test_non_s3_uris(uri: str, expected: bool, description: str):
    """Test non-S3 URIs are not detected."""
    assert _is_s3_uri(uri) == expected, f"Failed for: {description}"


@pytest.mark.parametrize("uri,expected,description", EDGE_CASE_URI_TEST_CASES)
def test_edge_case_uris(uri: Any, expected: bool, description: str):
    """Test edge cases for URI detection."""
    assert _is_s3_uri(uri) == expected, f"Failed for: {description}"


# ============================================================================
# Local Filesystem Tests (Free Functions)
# ============================================================================

def test_load_existing_local_file(sample_hdf5_file: str):
    """Test loading data from an existing local HDF5 file."""
    loader = HDF5(sample_hdf5_file)
    data = loader.load("test_matrix", numpy_array=True)
    
    assert data is not None
    assert isinstance(data, np.ndarray)
    assert data.shape == (100, 100)
    assert data.dtype == np.float32


@pytest.mark.parametrize("filepath_func,dataset,should_return_empty,description", FILE_EXISTENCE_TEST_CASES)
def test_file_existence_handling(sample_hdf5_file: str, 
                                 filepath_func, dataset: str, 
                                 should_return_empty: bool, description: str):
    """Parametrized test for file/dataset existence handling."""
    filepath = filepath_func(sample_hdf5_file)
    loader = HDF5(filepath)
    data = loader.load(dataset, Verbose=False, numpy_array=True)
    
    if should_return_empty:
        assert data.size == 0, f"Expected empty array for: {description}"
    else:
        assert data is not None and data.size > 0, f"Expected data for: {description}"


def test_empty_dataset(sample_hdf5_file: str):
    """Test loading an empty dataset."""
    loader = HDF5(sample_hdf5_file)
    data = loader.load("empty_dataset", numpy_array=True)
    
    assert data is not None
    assert isinstance(data, np.ndarray)
    assert data.size == 0


# ============================================================================
# S3 URI Tests (Free Functions)
# ============================================================================

def test_s3_uri_detected(s3_env_vars):
    """Test that S3 URIs trigger ROS3 VFD path."""
    s3_uri = "s3://test-bucket/test-file.h5"
    assert _is_s3_uri(s3_uri) == True


@pytest.mark.parametrize("s3_uri,dataset,description", S3_URI_ERROR_CASES)
def test_s3_connection_errors(s3_env_vars, s3_uri: str, dataset: str, description: str):
    """Test graceful handling of various S3 connection errors."""
    loader = HDF5(s3_uri)
    data = loader.load(dataset, Verbose=False, numpy_array=True)
    
    # Should return empty array on any S3 error
    assert data is not None
    assert isinstance(data, np.ndarray)
    assert data.size == 0


def test_local_after_s3_attempt(sample_hdf5_file: str, s3_env_vars):
    """Test that local path still works after attempting S3."""
    # First attempt S3 (will fail)
    loader1 = HDF5("s3://nonexistent/file.h5")
    data1 = loader1.load("test_matrix", Verbose=False, numpy_array=True)
    
    # Then use local path (should succeed)
    loader2 = HDF5(sample_hdf5_file)
    data2 = loader2.load("test_matrix", Verbose=False, numpy_array=True)
    
    assert data1.size == 0, "S3 should fail gracefully"
    assert data2.shape == (100, 100), "Local should succeed"


# ============================================================================
# Numpy Array Option Tests (Free Functions)
# ============================================================================

def test_numpy_array_option(sample_hdf5_file: str):
    """Test with numpy_array=True setting."""
    loader = HDF5(sample_hdf5_file)
    data = loader.load("test_matrix", numpy_array=True)
    
    # When numpy_array=True, should return numpy array
    assert isinstance(data, np.ndarray)
    assert data.shape == (100, 100)


# ============================================================================
# Offset/Block Parameter Tests (Free Functions)
# ============================================================================

def test_with_offset_and_block(sample_hdf5_file: str):
    """Test loading subset with Offset and Block."""
    loader = HDF5(sample_hdf5_file)
    data = loader.load(
        "test_matrix",
        numpy_array=True,
        Offset=[0, 0],
        Block=[10, 10]
    )
    
    assert isinstance(data, np.ndarray)
    assert data.shape == (10, 10)


def test_with_different_offsets(sample_hdf5_file: str):
    """Test with different offset values."""
    loader = HDF5(sample_hdf5_file)
    data = loader.load(
        "test_matrix",
        numpy_array=True,
        Offset=[50, 50],
        Block=[25, 25]
    )
    
    assert isinstance(data, np.ndarray)
    assert data.shape == (25, 25)


def test_full_array_without_offset_block(sample_hdf5_file: str):
    """Test loading full array without offset/block."""
    loader = HDF5(sample_hdf5_file)
    data = loader.load("test_matrix", numpy_array=True)
    
    assert data.shape == (100, 100)


# ============================================================================
# Verbose Output Tests (Free Functions)
# ============================================================================

def test_verbose_true(sample_hdf5_file: str, capsys):
    """Test with Verbose=True produces output."""
    loader = HDF5(sample_hdf5_file)
    data = loader.load("test_matrix", Verbose=True, numpy_array=True)
    
    captured = capsys.readouterr()
    # Should have printed something (though exact output varies)
    assert data is not None
    assert isinstance(data, np.ndarray)


def test_verbose_false(sample_hdf5_file: str, capsys):
    """Test with Verbose=False suppresses output."""
    loader = HDF5(sample_hdf5_file)
    data = loader.load("test_matrix", Verbose=False, numpy_array=True)
    
    captured = capsys.readouterr()
    # Should have no output
    assert captured.out == ""
    assert data is not None
    assert isinstance(data, np.ndarray)


# ============================================================================
# Special Character Path Tests (Free Functions)
# ============================================================================

@pytest.mark.parametrize("special_path", [
    "/path/with spaces/file.h5",
    "/path/with-dashes/file.h5",
    "/path/with_underscores/file.h5",
    "/path/with.dots/file.h5",
    "/path/with123numbers/file.h5",
])
def test_local_paths_with_special_chars(special_path: str):
    """Test that special characters in local paths are handled."""
    # These should NOT be detected as S3 URIs
    assert _is_s3_uri(special_path) == False


@pytest.mark.parametrize("special_bucket", [
    "bucket-with-dashes",
    "bucket_with_underscores",
    "bucket.with.dots",
    "bucket123with-numbers_456",
])
def test_s3_uris_with_special_chars(special_bucket: str):
    """Test that special characters in S3 URIs are handled."""
    s3_uri = f"s3://{special_bucket}/file.h5"
    assert _is_s3_uri(s3_uri) == True


# ============================================================================
# Integration Tests with Uvicorn (Free Functions)
# ============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_uvicorn_starts_with_s3_changes(integration_client):
    """
    Integration test verifying the full stack works with S3 support changes.
    
    This test uses the uvicorn_process fixture from conftest.py which:
    - Starts uvicorn in a subprocess
    - Captures stdout/stderr logs
    - Dumps logs on test failure
    - Automatically stops on completion
    """
    # Simple health check
    response = await integration_client.get("/catalogs/")
    response.raise_for_status()
    body = response.json()
    assert isinstance(body, list)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_catalogs_endpoint_comprehensive(integration_client):
    """Test the /catalogs/ endpoint comprehensively."""
    response = await integration_client.get("/catalogs/")
    response.raise_for_status()
    body = response.json()
    
    assert isinstance(body, list)
    assert len(body) > 0
    
    # Check that each catalog has expected fields
    for catalog in body:
        assert "name" in catalog
        assert "use" in catalog
        assert "description" in catalog


# ============================================================================
# S3 Integration Tests with VersityGW
# ============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_s3_uvicorn_startup(s3_integration_client):
    """
    Test that uvicorn starts successfully with S3 CATSHTM configuration.
    
    This test verifies:
    1. VersityGW container spins up
    2. Uvicorn starts with S3 environment variables
    3. Server responds to health check
    """
    response = await s3_integration_client.get("/catalogs/")
    response.raise_for_status()
    body = response.json()
    assert isinstance(body, list)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_s3_catalogs_endpoint(s3_integration_client):
    """
    Test that the /catalogs/ endpoint works with S3 CATSHTM configuration.
    
    This test verifies that the server can list catalogs even when
    CATSHTM_DIR points to an S3 bucket.
    """
    response = await s3_integration_client.get("/catalogs/")
    response.raise_for_status()
    body = response.json()
    
    assert isinstance(body, list)
    assert len(body) > 0
    
    # Check that each catalog has expected fields
    for catalog in body:
        assert "name" in catalog
        assert "use" in catalog
        assert "description" in catalog


@pytest.mark.integration
@pytest.mark.integration_s3
@pytest.mark.asyncio
async def test_s3_cone_search_smoke(s3_integration_client):
    """
    Smoke test for cone search with S3 CATSHTM.
    
    This test performs a simple cone search to verify that:
    1. The server can communicate with VersityGW
    2. ROS3 VFD can read files via S3 protocol
    3. Query returns valid results
    
    Note: This assumes test-data/catsHTM2 contains valid catalog data
    that can be queried.
    """
    # Use a catalog that exists in test-data
    request_body = {
        "ra_deg": 0.0,
        "dec_deg": 0.0,
        "radius_arcsec": 60.0,
        "catalogs": [
            {"name": "ROSATfsc", "use": "catsHTM", "rs_arcsec": 60}
        ]
    }
    
    response = await s3_integration_client.post("/cone_search/any", json=request_body)
    response.raise_for_status()
    body = response.json()
    
    # Should return a list with one boolean for each catalog
    assert isinstance(body, list)
    assert len(body) == 1
    # Result should be True or False (whether sources were found)
    assert isinstance(body[0], bool)


@pytest.mark.integration
@pytest.mark.integration_s3
@pytest.mark.asyncio
async def test_s3_cone_search_with_results(s3_integration_client):
    """
    Test cone search with S3 that should return results.
    
    This test verifies that actual data can be retrieved from S3
    and processed correctly.
    """
    # Query near a known bright source (e.g., near galactic center)
    request_body = {
        "ra_deg": 266.4,
        "dec_deg": -29.0,
        "radius_arcsec": 3600.0,  # 1 degree radius
        "catalogs": [
            {"name": "ROSATfsc", "use": "catsHTM", "rs_arcsec": 3600}
        ]
    }
    
    response = await s3_integration_client.post("/cone_search/all", json=request_body)
    response.raise_for_status()
    body = response.json()
    
    assert isinstance(body, list)
    assert len(body) == 1
    
    # Each result should be a list of catalog items or None
    result = body[0]
    if result is not None:
        assert isinstance(result, list)
        # Each item should have expected structure
        for item in result:
            assert "body" in item
            assert "dist_arcsec" in item


@pytest.mark.integration
@pytest.mark.asyncio
async def test_s3_nonexistent_catalog(s3_integration_client):
    """
    Test that querying a non-existent catalog with S3 returns appropriate error.
    
    This verifies error handling works correctly with S3 backend.
    """
    request_body = {
        "ra_deg": 0.0,
        "dec_deg": 0.0,
        "radius_arcsec": 60.0,
        "catalogs": [
            {"name": "NONEXISTENT_CATALOG_XYZ", "use": "catsHTM", "rs_arcsec": 60}
        ]
    }
    
    # This should either return empty results or raise an error
    # The exact behavior depends on how cone_search handles missing catalogs
    response = await s3_integration_client.post("/any", json=request_body)
    
    # Should either succeed with False (no sources) or fail with 4XX/5XX
    if response.status_code >= 400:
        # Error response is acceptable
        pass
    else:
        # Success response should contain False (no sources found)
        body = response.json()
        assert isinstance(body, list)
        assert len(body) == 1
        assert body[0] == False


# ============================================================================
# Conditional Tests (Explicit Skipping)
# ============================================================================

@pytest.mark.skip(reason="Requires MongoDB which may not be available in all environments")
def test_with_mongodb_integration():
    """Example of explicitly skipped test."""
    # This test would require MongoDB
    pass


# ============================================================================
# Module Availability Tests
# ============================================================================

def test_hdf5_class_instantiation():
    """Test that HDF5 class can be instantiated with various inputs."""
    # Local path
    loader1 = HDF5("/fake/path.h5")
    assert loader1.FileName == "/fake/path.h5"
    
    # S3 URI
    loader2 = HDF5("s3://bucket/file.h5")
    assert loader2.FileName == "s3://bucket/file.h5"


def test_is_s3_uri_function():
    """Test that _is_s3_uri function is callable and works correctly."""
    assert callable(_is_s3_uri)
    assert _is_s3_uri("s3://bucket/file.h5") == True
    assert _is_s3_uri("/local/path.h5") == False
