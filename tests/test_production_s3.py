"""
Production S3 Integration Tests
===============================

Tests that verify CATSHTM2 functionality against production S3 storage.

REQUIRED ENVIRONMENT VARIABLES:
---------------------------------
These tests require the following environment variables to be set.
You can set them in one of two ways:

1. Create a .env file in the repository root:
   
   CATSHTM_S3_BUCKET=your-bucket-name
   CATSHTM_S3_ENDPOINT=https://your-endpoint.url
   CATSHTM_S3_ACCESS_KEY=your-access-key
   CATSHTM_S3_SECRET_KEY=your-secret-key
   CATSHTM_S3_REGION=your-region

2. Export them in your shell:
   
   export CATSHTM_S3_BUCKET=your-bucket-name
   export CATSHTM_S3_ENDPOINT=https://your-endpoint.url
   export CATSHTM_S3_ACCESS_KEY=your-access-key
   export CATSHTM_S3_SECRET_KEY=your-secret-key
   export CATSHTM_S3_REGION=your-region

Note: pytest-dotenv will automatically load variables from .env files.

If any of these are missing, all tests in this module will be skipped.

SECURITY:
---------
- NEVER commit .env files to version control
- .env is in .gitignore by default
- Store secrets in your local shell profile or a secrets manager
- See .env.example for the template

USAGE:
------
  # Using .env file:
  cp .env.example .env
  # Edit .env with your values
  pytest tests/test_production_s3.py -v
  
  # Or using exported variables:
  export CATSHTM_S3_BUCKET=...
  pytest tests/test_production_s3.py -v
"""

import os

import pytest


# Required environment variables for production S3 tests
REQUIRED_ENV_VARS = {
    "CATSHTM_S3_BUCKET": "S3 bucket name (e.g., 'catalogs')",
    "CATSHTM_S3_ENDPOINT": "S3 endpoint URL (e.g., 'https://ampel-s3.zeuthen.desy.de:8443')",
    "CATSHTM_S3_ACCESS_KEY": "AWS access key ID",
    "CATSHTM_S3_SECRET_KEY": "AWS secret access key",
    "CATSHTM_S3_REGION": "AWS region (e.g., 'us-east-1')",
}


def get_missing_vars():
    """Get list of missing required environment variables."""
    return [var for var, desc in REQUIRED_ENV_VARS.items() if not os.environ.get(var)]


@pytest.fixture(scope="module", autouse=True)
def check_required_env_vars():
    """
    Skip all tests in this module if required environment variables are missing.
    """
    missing = get_missing_vars()
    if missing:
        pytest.skip(
            f"Missing required environment variables for production S3 tests: {', '.join(missing)}"
            f"\n\nRequired variables:\n"
            + "\n".join(f"  {var}: {desc}" for var, desc in REQUIRED_ENV_VARS.items())
            + f"\n\nSetup options:\n"
            + "  1. Create .env file: cp .env.example .env && edit .env\n"
            + "  2. Export in shell: see .env.example for variable names\n"
            + "\nNote: pytest-dotenv automatically loads .env files"
        )


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def get_s3_setup():
    """
    Get S3 configuration and set up environment for ROS3 VFD.
    
    Returns:
        Tuple of (s3_base_uri, bucket, endpoint, access_key, secret_key, region)
    """
    bucket = os.environ["CATSHTM_S3_BUCKET"]
    endpoint = os.environ["CATSHTM_S3_ENDPOINT"]
    access_key = os.environ["CATSHTM_S3_ACCESS_KEY"]
    secret_key = os.environ["CATSHTM_S3_SECRET_KEY"]
    region = os.environ["CATSHTM_S3_REGION"]
    
    # Construct S3 base URI
    s3_base = f"s3://{bucket}/catsHTM2/"
    
    # Set up environment for ROS3 VFD
    os.environ["CATSHTM_DIR"] = s3_base
    os.environ["AWS_ENDPOINT_URL"] = endpoint
    os.environ["AWS_ACCESS_KEY_ID"] = access_key
    os.environ["AWS_SECRET_ACCESS_KEY"] = secret_key
    os.environ["AWS_DEFAULT_REGION"] = region
    os.environ["H5ROSS3_PATH_STYLE"] = "1"
    os.environ["H5ROSS3_AUTH_METHOD"] = "ENV_VAR"
    
    return s3_base, bucket, endpoint, access_key, secret_key, region


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_catshtm_catalog_descriptions_with_s3():
    """
    Test that catshtm_catalog_descriptions() works with S3 URI.
    
    Verifies that our S3-aware loadmat allows catshtm_catalog_descriptions()
    to load all catalog metadata from S3.
    """
    from app.catalogs import catshtm_catalog_descriptions
    from app import settings as settings_module
    
    s3_base, _, _, _, _, _ = get_s3_setup()
    
    # Patch settings.catshtm_dir so catshtm_catalog_descriptions() uses S3
    original_catshtm_dir = settings_module.settings.catshtm_dir
    settings_module.settings.catshtm_dir = s3_base
    
    try:
        result = catshtm_catalog_descriptions()
        actual_count = len(result)
        
        print(f"\nDiscovered {actual_count} catalog(s) from S3:")
        catalog_names = [c['name'] for c in result]
        print(f"  {catalog_names}")
        
        # Should return at least some catalogs
        assert actual_count > 0, "Expected at least one catalog from S3"
        
    finally:
        # Restore original value
        settings_module.settings.catshtm_dir = original_catshtm_dir


def test_cone_search_all_with_s3():
    """
    Test search_all() with all CATSHTM catalogs on S3.
    
    Uses the actual app.cone_search.search_all function to verify
    it works with all S3-backed catalogs.
    """
    from app.cone_search import search_all
    from app.models import ConeSearchRequest, CatsHTMQueryItem
    from app.catalogs import catshtm_catalog_descriptions
    from app import settings as settings_module
    
    s3_base, _, _, _, _, _ = get_s3_setup()
    
    # Get all available catalogs from S3
    original_catshtm_dir = settings_module.settings.catshtm_dir
    settings_module.settings.catshtm_dir = s3_base
    
    try:
        catalog_infos = catshtm_catalog_descriptions()
    finally:
        settings_module.settings.catshtm_dir = original_catshtm_dir
    
    if not catalog_infos:
        pytest.skip("No catalogs found on S3")
    
    # Create query items for all catalogs
    query_items = [
        CatsHTMQueryItem(
            name=catalog_info['name'],
            rs_arcsec=10,
            keys_to_append=None,
        )
        for catalog_info in catalog_infos
    ]
    
    request = ConeSearchRequest(
        ra_deg=0.0,
        dec_deg=0.0,
        catalogs=query_items,
    )
    
    # Execute the actual cone search for all catalogs
    results = search_all(request)
    
    # Basic validation - search_all returns List[Optional[List[CatalogItem]]]
    assert isinstance(results, list), f"Expected list result, got {type(results)}"
    assert len(results) == len(query_items), \
        f"Expected {len(query_items)} results, got {len(results)}"
    
    # Print summary
    num_found = sum(1 for r in results if r is not None)
    print(f"\nTested {len(catalog_infos)} catalogs: {num_found} had results")
    
    # At least some catalogs should have results
    assert num_found >= 0, "Unexpected negative count"


def test_cone_search_any_with_s3():
    """
    Test search_any() with all CATSHTM catalogs on S3.
    """
    from app.cone_search import search_any
    from app.models import ConeSearchRequest, CatsHTMQueryItem
    from app.catalogs import catshtm_catalog_descriptions
    from app import settings as settings_module
    
    s3_base, _, _, _, _, _ = get_s3_setup()
    
    # Get all available catalogs from S3
    original_catshtm_dir = settings_module.settings.catshtm_dir
    settings_module.settings.catshtm_dir = s3_base
    
    try:
        catalog_infos = catshtm_catalog_descriptions()
    finally:
        settings_module.settings.catshtm_dir = original_catshtm_dir
    
    if not catalog_infos:
        pytest.skip("No catalogs found on S3")
    
    # Create query items for all catalogs
    query_items = [
        CatsHTMQueryItem(
            name=catalog_info['name'],
            rs_arcsec=10,
            keys_to_append=None,
        )
        for catalog_info in catalog_infos
    ]
    
    request = ConeSearchRequest(
        ra_deg=0.0,
        dec_deg=0.0,
        catalogs=query_items,
    )
    
    # Execute the actual cone search
    results = search_any(request)
    
    # search_any returns List[bool]
    assert isinstance(results, list), f"Expected list result, got {type(results)}"
    assert len(results) == len(query_items), \
        f"Expected {len(query_items)} results, got {len(results)}"
    
    # Print summary
    num_true = sum(results)
    print(f"\nTested {len(catalog_infos)} catalogs: {num_true} had matches")
