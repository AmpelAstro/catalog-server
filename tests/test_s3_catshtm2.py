"""
Unit tests for S3-backed CATSHTM2 support.

Tests exercise application code that handles S3 URIs:
- URI detection (_is_s3_uri)
- HDF5 class with S3 support
- loadmat wrapper for MATLAB files
"""

import os
import tempfile
from pathlib import Path
from typing import Generator

import pytest
import h5py
import numpy as np

# Direct imports - will raise ImportError if not available (intentional)
from app.catsHTM.class_HDF5 import HDF5, _is_s3_uri


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


# ============================================================================
# URI Detection Tests
# ============================================================================

S3_URI_TEST_CASES = [
    ("s3://bucket/file.h5", True, "Valid S3 URI"),
    ("s3://my-bucket/path/to/file.h5", True, "Nested S3 URI"),
    ("s3://bucket-123/data.h5", True, "Bucket with numbers"),
    ("s3://bucket-with-dashes/file.h5", True, "Bucket with dashes"),
    ("s3://bucket_with_underscores/file.h5", True, "Bucket with underscores"),
]

NON_S3_URI_TEST_CASES = [
    ("/local/path/file.h5", False, "Absolute local path"),
    ("relative/path/file.h5", False, "Relative local path"),
    ("http://example.com/file.h5", False, "HTTP URL"),
    ("https://example.com/file.h5", False, "HTTPS URL"),
    ("ftp://example.com/file.h5", False, "FTP URL"),
    ("", False, "Empty string"),
    ("s3:/bucket/file.h5", False, "Malformed S3 URI (single slash)"),
]

EDGE_CASE_URI_TEST_CASES = [
    (None, False, "None input"),
    (123, False, "Integer input"),
    ("s3:///", True, "Triple slash"),
]


@pytest.mark.parametrize("uri,expected,description", S3_URI_TEST_CASES)
def test_valid_s3_uris(uri: str, expected: bool, description: str):
    """Test that valid S3 URIs are detected correctly."""
    assert _is_s3_uri(uri) == expected


@pytest.mark.parametrize("uri,expected,description", NON_S3_URI_TEST_CASES)
def test_non_s3_uris(uri: str, expected: bool, description: str):
    """Test that non-S3 URIs are rejected correctly."""
    assert _is_s3_uri(uri) == expected


@pytest.mark.parametrize("uri,expected,description", EDGE_CASE_URI_TEST_CASES)
def test_edge_case_uris(uri, expected: bool, description: str):
    """Test edge cases for URI detection."""
    assert _is_s3_uri(uri) == expected


# ============================================================================
# HDF5 Class Tests
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
    # This is exposed as a module-level function
    assert callable(_is_s3_uri)
    assert _is_s3_uri("s3://bucket/file.h5") == True
    assert _is_s3_uri("/local/file.h5") == False


def test_load_existing_local_file(sample_hdf5_file: str):
    """Test loading data from a local HDF5 file."""
    loader = HDF5(sample_hdf5_file)
    
    # Load matrix
    data = loader.load("test_matrix", numpy_array=True)
    assert isinstance(data, np.ndarray)
    assert data.shape == (100, 100)
    
    # Load vector
    data = loader.load("test_vector", numpy_array=True)
    assert isinstance(data, np.ndarray)
    assert data.shape == (1000,)
    
    # Load scalar
    data = loader.load("test_scalar", numpy_array=True)
    assert isinstance(data, (np.ndarray, float, int))


def test_empty_dataset(sample_hdf5_file: str):
    """Test loading empty datasets."""
    loader = HDF5(sample_hdf5_file)
    data = loader.load("empty_dataset", numpy_array=True)
    assert isinstance(data, np.ndarray)
    assert data.size == 0


def test_numpy_array_option(sample_hdf5_file: str):
    """Test numpy_array parameter."""
    loader = HDF5(sample_hdf5_file)
    
    # With numpy_array=True
    data_np = loader.load("test_matrix", numpy_array=True)
    assert isinstance(data_np, np.ndarray)
    
    # With numpy_array=False
    data_raw = loader.load("test_matrix", numpy_array=False)
    # Raw data can be various types depending on h5py version
    assert data_raw is not None


def test_with_offset_and_block(sample_hdf5_file: str):
    """Test loading with offset and block parameters."""
    loader = HDF5(sample_hdf5_file)
    
    # Load subset of matrix
    data = loader.load(
        "test_matrix", 
        numpy_array=True, 
        Offset=[0, 0], 
        Block=[10, 10],
        Verbose=False
    )
    assert isinstance(data, np.ndarray)
    assert data.shape == (10, 10)


def test_full_array_without_offset_block(sample_hdf5_file: str):
    """Test loading full array without specifying offset/block."""
    loader = HDF5(sample_hdf5_file)
    
    data = loader.load("test_matrix", numpy_array=True, Verbose=False)
    assert isinstance(data, np.ndarray)
    assert data.shape == (100, 100)


def test_verbose_false(sample_hdf5_file: str, capsys):
    """Test that Verbose=False suppresses output."""
    loader = HDF5(sample_hdf5_file)
    loader.load("test_matrix", numpy_array=True, Verbose=False)
    captured = capsys.readouterr()
    assert captured.out == ""


def test_local_paths_with_special_chars():
    """Test HDF5 class with special characters in local paths."""
    special_paths = [
        "/path/with spaces/file.h5",
        "/path/with-dashes/file.h5",
        "/path/with_underscores/file.h5",
        "/path/with.dots/file.h5",
    ]
    
    for path in special_paths:
        loader = HDF5(path)
        assert loader.FileName == path


def test_s3_uris_with_special_chars():
    """Test HDF5 class with special characters in S3 URIs."""
    special_buckets = [
        "bucket-123",
        "bucket_with_underscores",
        "bucket.with.dots",
    ]
    
    for bucket in special_buckets:
        uri = f"s3://{bucket}/file.h5"
        loader = HDF5(uri)
        assert loader.FileName == uri
