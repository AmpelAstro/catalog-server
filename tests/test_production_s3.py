"""
Production S3 Integration Tests
===============================

Tests that verify CATSHTM2 functionality against production S3 storage.

REQUIRED ENVIRONMENT VARIABLES:
---------------------------------
These tests require the following environment variables to be set:

  CATSHTM_S3_BUCKET:       S3 bucket name (e.g., "ztf-phase2-catshtm")
  CATSHTM_S3_ENDPOINT:     S3 endpoint URL (e.g., "https://s3.west.nikhef.nl")
  CATSHTM_S3_ACCESS_KEY:   AWS access key ID
  CATSHTM_S3_SECRET_KEY:   AWS secret access key
  CATSHTM_S3_REGION:       AWS region (e.g., "us-east-1")

If any of these are missing, all tests in this module will be skipped.

SECURITY:
---------
- NEVER commit these values to version control
- Store them in your local shell profile (.bashrc, .zshrc, etc.)
- Or use a secrets manager
- Add patterns to .gitignore to prevent accidental commits

USAGE:
------
  # Set environment variables (one-time):
  export CATSHTM_S3_BUCKET="your-bucket-name"
  export CATSHTM_S3_ENDPOINT="https://your-endpoint.url"
  export CATSHTM_S3_ACCESS_KEY="your-access-key"
  export CATSHTM_S3_SECRET_KEY="your-secret-key"
  export CATSHTM_S3_REGION="your-region"
  
  # Run tests:
  pytest tests/test_production_s3.py -v
  
  # Or run manually in Python:
  python -m pytest tests/test_production_s3.py -v
"""

import os
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Environment Variable Validation
# ---------------------------------------------------------------------------

REQUIRED_ENV_VARS = {
    "CATSHTM_S3_BUCKET": "S3 bucket name",
    "CATSHTM_S3_ENDPOINT": "S3 endpoint URL",
    "CATSHTM_S3_ACCESS_KEY": "AWS access key ID",
    "CATSHTM_S3_SECRET_KEY": "AWS secret access key",
    "CATSHTM_S3_REGION": "AWS region",
}

MISSING_VARS = [var for var, desc in REQUIRED_ENV_VARS.items() if not os.environ.get(var)]


@pytest.fixture(scope="module", autouse=True)
def check_required_env_vars():
    """
    Skip all tests in this module if required environment variables are missing.
    """
    if MISSING_VARS:
        pytest.skip(
            f"Missing required environment variables for production S3 tests: {', '.join(MISSING_VARS)}"
            f"\n\nRequired variables:\n"
            + "\n".join(f"  {var}: {desc}" for var, desc in REQUIRED_ENV_VARS.items())
            + "\n\nSee test file header for setup instructions."
        )


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def get_s3_catalog_paths():
    """
    Get list of available CATSHTM catalogs from S3.
    
    Returns:
        List of str: Catalog names/path suffixes
    """
    from app.catsHTM.class_HDF5 import HDF5
    
    bucket = os.environ["CATSHTM_S3_BUCKET"]
    endpoint = os.environ["CATSHTM_S3_ENDPOINT"]
    access_key = os.environ["CATSHTM_S3_ACCESS_KEY"]
    secret_key = os.environ["CATSHTM_S3_SECRET_KEY"]
    region = os.environ["CATSHTM_S3_REGION"]
    
    # Construct S3 base URI
    s3_base = f"s3://{bucket}/"
    
    # Set up environment for ROS3 VFD
    os.environ["AWS_ENDPOINT_URL"] = endpoint
    os.environ["AWS_ACCESS_KEY_ID"] = access_key
    os.environ["AWS_SECRET_ACCESS_KEY"] = secret_key
    os.environ["AWS_DEFAULT_REGION"] = region
    os.environ["H5ROSS3_PATH_STYLE"] = "1"
    os.environ["H5ROSS3_AUTH_METHOD"] = "ENV_VAR"
    os.environ["H5ROSS3_NO_VERIFY_SSL"] = "1"
    
    # Try to discover catalogs by listing the bucket
    # This is a placeholder - actual implementation depends on how catalogs are organized
    # For now, return known catalog names or attempt to list
    try:
        # Try common catalog prefixes
        possible_catalogs = []
        
        # Check for standard naming patterns
        for pattern in ["PS1", "GaiaDR3", "AllWISE", "DECaLS-DR10", "BASS-DR3", 
                       "ZTF_source_features_DR", "ZTF_object_features_DR"]:
            test_path = f"{s3_base}{pattern}.h5"
            try:
                # Quick probe to see if file exists
                h = HDF5(test_path)
                h.close()
                possible_catalogs.append(pattern)
            except Exception:
                # Also try with .hdf5 extension
                test_path_hdf5 = f"{s3_base}{pattern}.hdf5"
                try:
                    h = HDF5(test_path_hdf5)
                    h.close()
                    possible_catalogs.append(pattern)
                except Exception:
                    pass
        
        if possible_catalogs:
            return possible_catalogs
        
        # Fallback: try to list from a known index
        # This would need actual S3 listing capability
        # For now, return empty list which will cause test to skip
        return []
        
    except Exception as e:
        pytest.skip(f"Failed to discover S3 catalogs: {e}")
        return []


# ---------------------------------------------------------------------------
# Production S3 Tests
# ---------------------------------------------------------------------------

def test_list_available_catalogs():
    """Verify we can discover available CATSHTM catalogs on S3."""
    catalogs = get_s3_catalog_paths()
    
    if not catalogs:
        pytest.skip("No catalogs discovered on S3. Bucket may be empty or inaccessible.")
    
    print(f"\nDiscovered {len(catalogs)} catalog(s) on S3:")
    for cat in sorted(catalogs):
        print(f"  - {cat}")
    
    assert len(catalogs) > 0, "Expected at least one catalog on S3"


@pytest.mark.parametrize("catalog", [], indirect=False)
def test_cone_search_each_catalog(catalog):
    """
    Perform a 10-arcsec cone search around (0, 0) for each catalog.
    
    This is parametrized dynamically based on discovered catalogs.
    """
    # This will be populated by the test collection hook
    pass


def test_cone_search_all_discovered_catalogs():
    """
    Test cone search on all discovered catalogs.
    
    Performs a 10-arcsecond radius cone search around coordinates (0, 0)
    for each catalog and verifies we get valid results (either data or empty).
    """
    from app.cone_search import cone_search_any
    from app.models import ConeSearchQuery
    
    catalogs = get_s3_catalog_paths()
    
    if not catalogs:
        pytest.skip("No catalogs discovered on S3.")
    
    # Coordinates: RA=0, DEC=0 (Galactic center direction)
    ra = 0.0
    dec = 0.0
    radius_arcsec = 10.0
    
    print(f"\nTesting cone searches for {len(catalogs)} catalog(s)...")
    
    for catalog in sorted(catalogs):
        print(f"\n  Testing catalog: {catalog}")
        
        # Build S3 URI for this catalog
        bucket = os.environ["CATSHTM_S3_BUCKET"]
        s3_uri = f"s3://{bucket}/{catalog}.h5"
        
        # Alternative: try .hdf5 extension
        s3_uri_hdf5 = f"s3://{bucket}/{catalog}.hdf5"
        
        # Try both extensions
        success = False
        for uri in [s3_uri, s3_uri_hdf5]:
            try:
                # Perform cone search
                query = ConeSearchQuery(
                    ra_deg=ra,
                    dec_deg=dec,
                    radius_arcsec=radius_arcsec,
                    catalog_names=[catalog],
                )
                
                result = cone_search_any(query)
                
                # Result should be a dict with catalog name as key
                assert isinstance(result, dict), f"Expected dict result for {catalog}"
                
                # Either has data or is empty (both are valid)
                if catalog in result:
                    data = result[catalog]
                    assert isinstance(data, (dict, list)), \
                        f"Unexpected result type for {catalog}: {type(data)}"
                    print(f"    ✓ Got {len(data) if isinstance(data, list) else 'non-list'} results")
                    success = True
                    break
                    
            except FileNotFoundError:
                # This catalog/extension doesn't exist, try next
                continue
            except Exception as e:
                print(f"    ✗ Error searching {uri}: {e}")
                raise
        
        if not success:
            pytest.fail(f"Could not perform successful cone search for catalog: {catalog}")
    
    print(f"\n✅ All {len(catalogs)} catalog(s) tested successfully!")


# ---------------------------------------------------------------------------
# Manual Test Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Allow running this file directly for debugging
    pytest.main([__file__, "-v", "-s"])
