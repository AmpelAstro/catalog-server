#!/usr/bin/env python3
# type: ignore
"""
Simplified Test: Consolidated Format vs Legacy Format Cone Search

Uses direct HDF5 access for both formats to avoid import conflicts.
Verifies that cone searches produce identical results.
"""

import math
import time
import numpy as np
import sys
import h5py
import os

# Must import hdf5plugin before h5py for ZSTD support
import hdf5plugin  # noqa: F401

sys.path.insert(0, '/Users/jakob/Documents/ZTF/catalog-server/app/catsHTM')
import io_consolidated


def degrees_to_radians(deg):
    """Convert degrees to radians."""
    return deg * math.pi / 180.0


def cosine_law_distance(ra1, dec1, ra2, dec2):
    """
    Calculate angular distance between two points on a sphere.
    
    Args:
        ra1, dec1: First point in radians
        ra2, dec2: Second point in radians
        
    Returns:
        Angular distance in radians
    """
    cos_dec1, sin_dec1 = np.cos(dec1), np.sin(dec1)
    cos_dec2, sin_dec2 = np.cos(dec2), np.sin(dec2)
    delta_ra = ra2 - ra1
    
    cos_dist = (np.cos(delta_ra) * cos_dec1 * cos_dec2 + sin_dec1 * sin_dec2)
    cos_dist = np.clip(cos_dist, -1.0, 1.0)
    return np.arccos(cos_dist)


def load_legacy_cosmos(legacy_dir):
    """
    Load all Cosmos data from legacy format files.
    
    Returns:
        dict mapping trixel_id to star data array
    """
    all_trixels = {}
    
    # Iterate through all HDF5 files
    for fname in os.listdir(legacy_dir):
        if not fname.startswith('Cosmos_htm_') or not fname.endswith('.hdf5'):
            continue
        
        fpath = os.path.join(legacy_dir, fname)
        with h5py.File(fpath, 'r') as f:
            for key in f.keys():
                if key.endswith('_Ind'):
                    continue  # Skip index datasets
                
                ds = f[key]
                if ds.ndim != 2 or ds.shape[0] != 27:
                    continue
                
                # Extract trixel ID from key (e.g., 'htm_266490')
                parts = key.split('_')
                if len(parts) >= 2:
                    try:
                        trixel_id = int(parts[-1])
                        # Transpose to (N_stars, 27) to match consolidated format
                        star_data = np.array(ds).T
                        all_trixels[trixel_id] = star_data
                    except ValueError:
                        pass
    
    return all_trixels


def load_legacy_index(legacy_dir):
    """
    Load HTM index from legacy format.
    
    Returns:
        tuple: (index_data, nside)
    """
    index_file = os.path.join(legacy_dir, 'Cosmos_htm.hdf5')
    with h5py.File(index_file, 'r') as f:
        for key in f.keys():
            if 'htm' in key.lower() or 'index' in key.lower():
                index_data = np.array(f[key])
                return index_data, index_data.shape[0]
    return None, None


def search_legacy_all_trixels(legacy_trixels, ra_center, dec_center, radius_rad):
    """
    Brute force search across all loaded trixels.
    
    Args:
        legacy_trixels: Dict mapping trixel_id to star data
        ra_center, dec_center: Search center in radians
        radius_rad: Search radius in radians
        
    Returns:
        Concatenated array of all stars within radius
    """
    all_results = []
    
    for trixel_id, star_data in legacy_trixels.items():
        if star_data.size == 0:
            continue
        
        ra_col = star_data[:, 0]
        dec_col = star_data[:, 1]
        
        dists = cosine_law_distance(ra_center, dec_center, ra_col, dec_col)
        mask = dists <= radius_rad
        
        if np.any(mask):
            all_results.append(star_data[mask])
    
    if all_results:
        return np.vstack(all_results)
    else:
        return np.empty((0, 27))


def search_consolidated(cat, ra_center, dec_center, radius_rad):
    """
    Search using ConsolidatedCatalog.
    
    Args:
        cat: ConsolidatedCatalog instance
        ra_center, dec_center: Search center in radians
        radius_rad: Search radius in radians
        
    Returns:
        Array of stars within radius
    """
    all_results = []
    
    # Iterate over all trixel IDs in the catalog
    for trixel_id in cat.trixel_ids:
        try:
            star_data = cat.get_trixel_data(trixel_id)
        except Exception:
            continue
        
        if star_data.size == 0:
            continue
        
        ra_col = star_data[:, 0]
        dec_col = star_data[:, 1]
        
        dists = cosine_law_distance(ra_center, dec_center, ra_col, dec_col)
        mask = dists <= radius_rad
        
        if np.any(mask):
            all_results.append(star_data[mask])
    
    if all_results:
        return np.vstack(all_results)
    else:
        return np.empty((0, cat.num_columns))


def sort_and_compare(results_a, results_b, tol=1e-10):
    """
    Sort both result sets by RA, Dec and compare.
    
    Returns:
        True if results match within tolerance
    """
    if results_a.size == 0 and results_b.size == 0:
        return True
    
    if results_a.shape != results_b.shape:
        print(f"    Shape mismatch: {results_a.shape} vs {results_b.shape}")
        return False
    
    # Sort by RA then Dec
    idx_a = np.lexsort((results_a[:, 1], results_a[:, 0]))
    idx_b = np.lexsort((results_b[:, 1], results_b[:, 0]))
    
    sorted_a = results_a[idx_a]
    sorted_b = results_b[idx_b]
    
    if not np.allclose(sorted_a, sorted_b, rtol=tol, atol=tol):
        max_diff = np.max(np.abs(sorted_a - sorted_b))
        print(f"    Values differ: max diff = {max_diff}")
        return False
    
    return True


def generate_random_point(seed=None):
    """Generate random point near Cosmos center."""
    if seed is not None:
        rng = np.random.default_rng(seed)
    else:
        rng = np.random.default_rng()
    
    ra_deg = 150.125 + rng.uniform(-0.5, 0.5)
    dec_deg = 2.2108 + rng.uniform(-0.5, 0.5)
    return ra_deg, dec_deg


def main():
    print("="*70)
    print("LEGACY vs CONSOLIDATED CONE SEARCH COMPARISON")
    print("="*70)
    
    # Paths
    legacy_dir = "/tmp/cosmos_download"
    consolidated_path = "/tmp/Cosmos_new_format.hdf5"
    
    # Load legacy data
    print("\nLoading legacy Cosmos data...")
    legacy_trixels = load_legacy_cosmos(legacy_dir)
    print(f"  Loaded {len(legacy_trixels)} trixels")
    total_legacy_stars = sum(t.shape[0] for t in legacy_trixels.values())
    print(f"  Total stars: {total_legacy_stars:,}")
    
    # Open consolidated catalog
    print("\nOpening consolidated Cosmos catalog...")
    with io_consolidated.ConsolidatedCatalog(consolidated_path) as cons_cat:
        print(f"  Trixels: {cons_cat.num_trixels}")
        print(f"  Stars: {cons_cat.total_stars:,}")
        
        # Run tests
        num_tests = 10
        radii_arcsec = [10, 50, 100, 200]
        
        passed = 0
        failed = 0
        
        for test_num in range(1, num_tests + 1):
            for radius in radii_arcsec:
                ra_deg, dec_deg = generate_random_point(seed=test_num * 100 + radius)
                radius_rad = degrees_to_radians(radius / 3600.0)
                
                print(f"\nTest {test_num}.{radii_arcsec.index(radius)+1}:")
                print(f"  Point: ({ra_deg:.4f}°, {dec_deg:.4f}°), Radius: {radius}\"arcsec")
                
                # Legacy search
                start = time.time()
                legacy_results = search_legacy_all_trixels(
                    legacy_trixels, degrees_to_radians(ra_deg), 
                    degrees_to_radians(dec_deg), radius_rad
                )
                elapsed_legacy = time.time() - start
                print(f"  Legacy: {len(legacy_results)} stars in {elapsed_legacy:.4f}s")
                
                # Consolidated search
                start = time.time()
                consolid_results = search_consolidated(
                    cons_cat, degrees_to_radians(ra_deg),
                    degrees_to_radians(dec_deg), radius_rad
                )
                elapsed_cons = time.time() - start
                print(f"  Consolidated: {len(consolid_results)} stars in {elapsed_cons:.4f}s")
                
                # Compare
                if sort_and_compare(legacy_results, consolid_results):
                    print(f"  ✅ Results match!")
                    passed += 1
                else:
                    print(f"  ❌ Results differ!")
                    failed += 1
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    total = passed + failed
    print(f"Tests: {passed}/{total} passed, {failed}/{total} failed")
    
    if failed == 0:
        print("\n✅ ALL TESTS PASSED - Formats are equivalent!")
        return 0
    else:
        print(f"\n❌ {failed} TEST(S) FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
