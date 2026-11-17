#!/usr/bin/env python
"""
Profile script for CATSHTM cone search performance.

Runs a cone search against GAIADR2 at specified (RA, Dec) with given radius
and measures execution time.

Usage:
    python profile_cone_search.py          # Default: 100 arcsec at (0, 0)
    python profile_cone_search.py 1.5      # Custom radius in arcsec at (0, 0)
    python profile_cone_search.py --random 10  # 10 random points with default radius
    python profile_cone_search.py --random 10 100  # 10 random points, radius=100 arcsec
    python -m cProfile -s cumulative profile_cone_search.py  # Detailed profiling
"""

import os
import sys
import time
import math
from pathlib import Path

# Load environment variables from .env file
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# Set up S3 environment for ROS3 VFD
os.environ["AWS_ENDPOINT_URL"] = os.environ["CATSHTM_S3_ENDPOINT"]
os.environ["AWS_ACCESS_KEY_ID"] = os.environ["CATSHTM_S3_ACCESS_KEY"]
os.environ["AWS_SECRET_ACCESS_KEY"] = os.environ["CATSHTM_S3_SECRET_KEY"]
os.environ["AWS_DEFAULT_REGION"] = os.environ["CATSHTM_S3_REGION"]
os.environ["H5ROSS3_PATH_STYLE"] = "1"
os.environ["H5ROSS3_AUTH_METHOD"] = "ENV_VAR"
os.environ["H5ROSS3_NO_VERIFY_SSL"] = "1"

# Set CATSHTM_DIR to S3 base
s3_base = f"s3://{os.environ['CATSHTM_S3_BUCKET']}/catsHTM2/"
os.environ["CATSHTM_DIR"] = s3_base

# Now run the cone search
from app.catsHTM.script import cone_search


def generate_random_point():
    """Generate a random (RA, Dec) point uniformly distributed over the sphere.
    
    Accounts for projection effects by:
    - Drawing sin(dec) uniformly from [-1, 1]
    - Converting to dec using arcsin
    - RA drawn uniformly from [0, 360]
    
    Returns:
        tuple: (ra_degrees, dec_degrees)
    """
    import random
    ra = random.uniform(0, 360)  # Uniform in RA
    sin_dec = random.uniform(-1, 1)  # Uniform in sin(dec) accounts for cos(dec) projection
    dec = math.degrees(math.asin(sin_dec))  # Convert to degrees
    return ra, dec


def profile_gaiadr2_cone_search(radius_arcsec=100.0, ra=None, dec=None):
    """Profile a cone search against GAIADR2.
    
    Args:
        radius_arcsec: Search radius in arcseconds (default: 100)
        ra: Right ascension in degrees (default: 0)
        dec: Declination in degrees (default: 0)
    """
    
    if ra is None:
        ra = 0.0  # degrees
    if dec is None:
        dec = 0.0  # degrees
    
    print(f"Running cone search: GAIADR2 at ({ra}, {dec}) with radius={radius_arcsec} arcsec")
    print("-" * 60)
    
    # Warm up
    _ = cone_search("GAIADR2", ra, dec, radius_arcsec, catalogs_dir=s3_base, verbose=False)
    
    # Profile
    iterations = 3
    times = []
    
    for i in range(iterations):
        start = time.perf_counter()
        cat_onlycone, ColCell, ColUnits = cone_search("GAIADR2", ra, dec, radius_arcsec, catalogs_dir=s3_base, verbose=False)
        elapsed = time.perf_counter() - start
        times.append(elapsed)
        
        num_objects = len(cat_onlycone) if cat_onlycone is not None and cat_onlycone.size > 0 else 0
        print(f"Iteration {i+1}: {elapsed:.3f}s, {num_objects} objects")
    
    avg_time = sum(times) / len(times)
    min_time = min(times)
    max_time = max(times)
    
    print("-" * 60)
    print(f"Average time: {avg_time:.3f}s")
    print(f"Min time: {min_time:.3f}s")
    print(f"Max time: {max_time:.3f}s")
    
    # Verify we got results
    assert cat_onlycone is not None, "cone_search returned None"
    
    num_found = cat_onlycone.shape[0] if cat_onlycone.size > 0 else 0
    print(f"\n✓ Success: Found {num_found} objects in GAIADR2")
    return avg_time, num_found


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Profile CATSHTM cone search")
    parser.add_argument("radius", type=float, nargs="?", default=100.0,
                       help="Search radius in arcseconds (default: 100)")
    parser.add_argument("--random", "-n", type=int, metavar="N",
                       help="Run N queries at random positions on the sphere")
    parser.add_argument("--seed", type=int, default=None,
                       help="Random seed for reproducibility")
    args = parser.parse_args()
    
    import random
    if args.seed is not None:
        random.seed(args.seed)
    
    if args.random:
        print(f"Running {args.random} random cone searches with radius={args.radius} arcsec\n")
        print("-" * 60)
        times = []
        for i in range(args.random):
            ra, dec = generate_random_point()
            start = time.perf_counter()
            cat_onlycone, ColCell, ColUnits = cone_search(
                "GAIADR2", ra, dec, args.radius, catalogs_dir=s3_base, verbose=False
            )
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            num_objects = len(cat_onlycone) if cat_onlycone is not None and cat_onlycone.size > 0 else 0
            print(f"Point {i+1:2d}: RA={ra:7.2f}°, Dec={dec:+7.2f}° | {elapsed:.3f}s | {num_objects} objects")
        
        print("-" * 60)
        avg_time = sum(times) / len(times)
        min_time = min(times)
        max_time = max(times)
        print(f"Average time: {avg_time:.3f}s")
        print(f"Min time: {min_time:.3f}s")
        print(f"Max time: {max_time:.3f}s")
    else:
        profile_gaiadr2_cone_search(radius_arcsec=args.radius)
