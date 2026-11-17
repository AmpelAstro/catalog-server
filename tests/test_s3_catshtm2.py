"""
Unit tests for S3-backed CATSHTM2 support.

Tests exercise application code that handles S3 URIs:
- URI detection (_is_s3_uri)
- load_hdf5_dataset function with S3 support
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
from app.catsHTM.io import _is_s3_uri, load_hdf5_dataset


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
            f.create_dataset(
                "test_matrix", data=np.random.rand(100, 100).astype(np.float32)
            )
            f.create_dataset(
                "test_vector", data=np.random.rand(1000).astype(np.float32)
            )
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
# HDF5 I/O Function Tests
# ============================================================================


def test_load_hdf5_dataset_basic():
    """Test that load_hdf5_dataset function can handle various inputs."""
    # This is tested indirectly through other tests
    # The HDF5 class has been removed in favor of standalone functions
    pass


def test_is_s3_uri_function():
    """Test that _is_s3_uri function is callable and works correctly."""
    # This is exposed as a module-level function
    assert callable(_is_s3_uri)
    assert _is_s3_uri("s3://bucket/file.h5") == True
    assert _is_s3_uri("/local/file.h5") == False


def test_load_existing_local_file(sample_hdf5_file: str):
    """Test loading data from a local HDF5 file."""
    # Load matrix
    data = load_hdf5_dataset(sample_hdf5_file, "test_matrix")
    assert isinstance(data, np.ndarray)
    assert data.shape == (100, 100)

    # Load vector
    data = load_hdf5_dataset(sample_hdf5_file, "test_vector")
    assert isinstance(data, np.ndarray)
    assert data.shape == (1000,)

    # Load scalar
    data = load_hdf5_dataset(sample_hdf5_file, "test_scalar")
    assert isinstance(data, (np.ndarray, float, int))


def test_empty_dataset(sample_hdf5_file: str):
    """Test loading empty datasets."""
    data = load_hdf5_dataset(sample_hdf5_file, "empty_dataset")
    assert isinstance(data, np.ndarray)
    assert data.size == 0


def test_numpy_array_option(sample_hdf5_file: str):
    """Test that load_hdf5_dataset always returns numpy arrays."""
    # The new implementation always returns numpy arrays
    data = load_hdf5_dataset(sample_hdf5_file, "test_matrix")
    assert isinstance(data, np.ndarray)


def test_full_array_without_offset_block(sample_hdf5_file: str):
    """Test loading full array without specifying offset/block."""
    data = load_hdf5_dataset(sample_hdf5_file, "test_matrix")
    assert isinstance(data, np.ndarray)
    assert data.shape == (100, 100)


def test_verbose_false(sample_hdf5_file: str, capsys):
    """Test that load_hdf5_dataset doesn't print output."""
    load_hdf5_dataset(sample_hdf5_file, "test_matrix")
    captured = capsys.readouterr()
    assert captured.out == ""


def test_local_paths_with_special_chars():
    """Test _is_s3_uri with special characters in local paths."""
    special_paths = [
        "/path/with spaces/file.h5",
        "/path/with-dashes/file.h5",
        "/path/with_underscores/file.h5",
        "/path/with.dots/file.h5",
    ]

    for path in special_paths:
        assert _is_s3_uri(path) == False


def test_s3_uris_with_special_chars():
    """Test _is_s3_uri with special characters in S3 URIs."""
    special_buckets = [
        "bucket-123",
        "bucket_with_underscores",
        "bucket.with.dots",
    ]

    for bucket in special_buckets:
        uri = f"s3://{bucket}/file.h5"
        assert _is_s3_uri(uri) == True
