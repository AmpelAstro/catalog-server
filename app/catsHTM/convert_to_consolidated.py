#!/usr/bin/env python3
# type: ignore
"""
Conversion Script: Original CATSHTM2 → Consolidated Format

Converts a single CATSHTM2 catalog (multiple files) into the consolidated
HDF5 format. Operates on one catalog at a time.

Usage:
    python convert_to_consolidated.py \
        --catalog-name GAIADR2 \
        --input-dir /path/to/catsHTM2/GAIA/DR2 \
        --output GAIADR2_CONSOLIDATED.hdf5 \
        [--chunk-stars 512] \
        [--chunk-cols 9] \
        [--compress]

Features:
    - Processes all trixel files in input directory
    - Preserves all original data
    - Adds column-wise chunking for S3 efficiency
    - Applies zstd compression
    - Shows progress bars with tqdm
    - Validates input files

Dependencies:
    - h5py
    - hdf5plugin (for zstd compression)
    - numpy
    - scipy (for .mat file reading)
    - tqdm
"""

import argparse
import glob
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import h5py
import numpy as np
import scipy.io

# Try to import hdf5plugin for zstd
try:
    import hdf5plugin
    HAS_ZSTD = True
except ImportError:
    HAS_ZSTD = False
    print("Warning: hdf5plugin not available. Compression disabled.")

# Try to import tqdm for progress bars
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    print("Warning: tqdm not available. Progress bars disabled.")


# Constants
DEFAULT_CHUNK_SHAPE = (512, 9)
ZSTD_FILTER_ID = 32015
ZSTD_LEVEL = 5


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Convert CATSHTM2 catalog to consolidated HDF5 format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Convert GAIADR2 with defaults
    python convert_to_consolidated.py \\
        --catalog-name GAIADR2 \\
        --input-dir ./catsHTM2/GAIA/DR2 \\
        --output GAIADR2_CONSOLIDATED.hdf5

    # Convert without compression
    python convert_to_consolidated.py \\
        --catalog-name TMASS \\
        --input-dir ./catsHTM2/2MASS \\
        --output TMASS_CONSOLIDATED.hdf5 \\
        --no-compress

    # Custom chunking
    python convert_to_consolidated.py \\
        --catalog-name MyCatalog \\
        --input-dir ./my_catalog \\
        --output my_catalog.hdf5 \\
        --chunk-stars 256 \\
        --chunk-cols 6
        """
    )
    
    parser.add_argument(
        "--catalog-name", 
        type=str, 
        required=True,
        help="Name of the catalog (e.g., GAIADR2, TMASS)"
    )
    
    parser.add_argument(
        "--input-dir",
        type=str,
        required=True,
        help="Directory containing original CATSHTM2 files"
    )
    
    parser.add_argument(
        "--output",
        type=str,
        required=True,
        help="Output consolidated HDF5 file path"
    )
    
    parser.add_argument(
        "--chunk-stars",
        type=int,
        default=DEFAULT_CHUNK_SHAPE[0],
        help=f"Number of stars per chunk (default: {DEFAULT_CHUNK_SHAPE[0]})"
    )
    
    parser.add_argument(
        "--chunk-cols",
        type=int,
        default=DEFAULT_CHUNK_SHAPE[1],
        help=f"Number of columns per chunk (default: {DEFAULT_CHUNK_SHAPE[1]})"
    )
    
    parser.add_argument(
        "--compress",
        action="store_true",
        default=True,
        dest="compress",
        help="Enable zstd compression (requires hdf5plugin)"
    )
    
    parser.add_argument(
        "--no-compress",
        action="store_false",
        dest="compress",
        help="Disable compression"
    )
    
    parser.add_argument(
        "--overwrite",
        action="store_true",
        default=False,
        help="Overwrite output file if it exists"
    )
    
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Print detailed processing information"
    )
    
    return parser.parse_args()


def find_catalog_files(input_dir: str, catalog_name: str) -> Tuple[Optional[str], Optional[str], List[str]]:
    """
    Find the index, ColCell, and trixel files for a catalog.
    
    Args:
        input_dir: Directory to search
        catalog_name: Base name of the catalog
        
    Returns:
        Tuple of (index_path, colcell_path, trixel_paths)
    """
    input_path = Path(input_dir)
    
    # Patterns to search
    index_patterns = [
        f"{catalog_name}_htm.hdf5",
        f"*{catalog_name}*_htm.hdf5",
        "*_htm.hdf5",
    ]
    
    colcell_patterns = [
        f"{catalog_name}_htmColCell.mat",
        f"*{catalog_name}*_htmColCell.mat",
        "*_htmColCell.mat",
        "*.mat",
    ]
    
    trixel_patterns = [
        f"{catalog_name}_htm_*.hdf5",
        f"*{catalog_name}*_htm_*.hdf5",
        "*_htm_*.hdf5",
    ]
    
    # Search for index file
    index_path = None
    for pattern in index_patterns:
        matches = list(input_path.glob(pattern))
        if matches:
            # Skip trixel files (they also match *_htm_*.hdf5)
            # Index files typically have format: Catalog_htm.hdf5 (2 underscores)
            # Trixel files have format: Catalog_htm_NNNNNN.hdf5 (3+ underscores)
            filtered = [m for m in matches if m.name.count('_') == 2]
            if not filtered:
                # Fallback: take files that DON'T have numbers after last underscore
                filtered = [m for m in matches if not any(c.isdigit() for c in m.stem.split('_')[-1])]
            if filtered:
                index_path = str(filtered[0])
                break
    
    # Search for ColCell file
    colcell_path = None
    for pattern in colcell_patterns:
        matches = list(input_path.glob(pattern))
        if matches:
            colcell_path = str(matches[0])
            break
    
    # Search for trixel files
    trixel_paths = []
    seen_files = set()
    for pattern in trixel_patterns:
        matches = list(input_path.glob(pattern))
        # Filter out index file (which might match *_htm_*.hdf5)
        # Trixel files have numbers in the name
        for m in matches:
            fname = str(m)
            if fname not in seen_files:
                # Check if it has a numeric suffix (trixel number)
                stem = m.stem
                last_part = stem.split('_')[-1]
                if last_part.isdigit():
                    trixel_paths.append(fname)
                    seen_files.add(fname)
    
    # Also directly check for common patterns
    direct_patterns = [
        f"{catalog_name}_htm_[0-9]*.hdf5",
        f"htm_[0-9]*.hdf5",
    ]
    for pattern in direct_patterns:
        matches = list(input_path.glob(pattern))
        for m in matches:
            fname = str(m)
            if fname not in seen_files:
                trixel_paths.append(fname)
                seen_files.add(fname)
    
    # Sort trixel files numerically
    trixel_paths.sort()
    
    return index_path, colcell_path, trixel_paths


def extract_trixel_info(trixel_file: str) -> Tuple[List[int], int, List[int], List[str]]:
    """
    Extract trixel IDs, dimensions, and dataset names from a trixel file.
    
    A single physical file can contain multiple trixels (datasets).
    
    Args:
        trixel_file: Path to a trixel HDF5 file
        
    Returns:
        Tuple of (trixel_ids, num_columns, star_counts, dataset_names)
    """
    with h5py.File(trixel_file, 'r') as f:
        # Get dataset names (excluding _Ind datasets)
        all_keys = list(f.keys())
        dataset_names = [k for k in all_keys if not k.endswith('_Ind')]
        
        if not dataset_names:
            raise ValueError(f"No valid datasets found in {trixel_file}")
        
        # Extract trixel IDs from dataset names
        trixel_ids = []
        star_counts = []
        
        for name in dataset_names:
            # Extract trixel ID from dataset name
            # Format: htm_NNNNNN or Catalog_htm_NNNNNN
            basename = name
            if '_htm_' in basename:
                parts = basename.split('_htm_')
                if len(parts) >= 2:
                    try:
                        trixel_id = int(parts[-1])
                        trixel_ids.append(trixel_id)
                    except ValueError:
                        trixel_ids.append(-1)
                else:
                    trixel_ids.append(-1)
            else:
                # Try to extract number from name
                parts = basename.split('_')
                for p in reversed(parts):
                    try:
                        trixel_id = int(p)
                        trixel_ids.append(trixel_id)
                        break
                    except ValueError:
                        continue
                else:
                    trixel_ids.append(-1)
            
            # Get star count from dataset
            ds = f[name]
            star_counts.append(ds.shape[1])
        
        # Get column count from first dataset
        first_ds = f[dataset_names[0]]
        num_columns = first_ds.shape[0]
        
        return trixel_ids, num_columns, star_counts, dataset_names


def count_total_stars(trixel_files: List[str], verbose: bool = False) -> Tuple[int, int, List[int], List[int]]:
    """
    Count total stars and collect trixel IDs from all trixel files.
    
    Args:
        trixel_files: List of trixel file paths
        verbose: Print progress
        
    Returns:
        Tuple of (total_stars, num_columns, trixel_ids, star_counts)
    """
    total_stars = 0
    num_columns = None
    all_trixel_ids = []
    all_star_counts = []
    
    iterator = trixel_files
    if HAS_TQDM:
        iterator = tqdm(trixel_files, desc="Analyzing trixels", unit="file")
    
    for tf in iterator:
        trixel_ids, ncols, star_counts, _ = extract_trixel_info(tf)
        
        if num_columns is None:
            num_columns = ncols
        elif ncols != num_columns:
            raise ValueError(f"Inconsistent column count: expected {num_columns}, got {ncols} in {tf}")
        
        all_trixel_ids.extend(trixel_ids)
        all_star_counts.extend(star_counts)
        total_stars += sum(star_counts)
    
    return total_stars, num_columns, all_trixel_ids, all_star_counts


def create_consolidated_file(
    output_path: str,
    catalog_name: str,
    index_data: np.ndarray,
    colcell: List[str],
    colunits: List[str],
    trixel_ids: List[int],
    star_counts: List[int],
    num_columns: int,
    total_stars: int,
    chunk_shape: Tuple[int, int],
    compress: bool,
    verbose: bool = False
) -> None:
    """
    Create the consolidated HDF5 file with all data.
    
    Args:
        output_path: Output file path
        catalog_name: Name of the catalog
        index_data: HTM index array
        colcell: Column names
        colunits: Column units
        trixel_ids: List of trixel IDs
        star_counts: List of star counts per trixel
        num_columns: Number of columns
        total_stars: Total number of stars
        chunk_shape: Chunk shape (stars, cols)
        compress: Enable compression
        verbose: Print progress
    """
    # Compute offsets
    offsets = np.cumsum([0] + star_counts).astype(np.int32)
    
    # Determine chunk shape for index
    index_chunk = (index_data.shape[0], 10000) if index_data.ndim == 2 else (10000,)
    
    # Create output file
    if verbose:
        print(f"Creating {output_path}...")
        print(f"  Catalog: {catalog_name}")
        print(f"  Trixels: {len(trixel_ids)}")
        print(f"  Stars: {total_stars:,}")
        print(f"  Columns: {num_columns}")
        print(f"  Chunk shape: {chunk_shape}")
        print(f"  Compression: {'enabled' if compress else 'disabled'}")
    
    with h5py.File(output_path, 'w') as fout:
        # String dtype for ColCell and ColUnits
        max_len = max(max(len(s) for s in colcell), max(len(s) for s in colunits)) + 2
        dt_string = h5py.string_dtype('ascii', max_len)
        
        # Create datasets
        
        # 1. Column metadata
        if verbose:
            print("  Writing column metadata...")
        fout.create_dataset('ColCell', data=np.array(colcell, dtype=dt_string))
        fout.create_dataset('ColUnits', data=np.array(colunits, dtype=dt_string))
        
        # 2. Index data
        if verbose:
            print("  Writing index data...")
        dcpl_index = h5py.h5p.create(h5py.h5p.DATASET_CREATE)
        dcpl_index.set_chunk(index_chunk)
        if compress and HAS_ZSTD:
            dcpl_index.set_filter(ZSTD_FILTER_ID, 0, (ZSTD_LEVEL,))
        fout.create_dataset('index', data=index_data, dcpl=dcpl_index)
        
        # 3. Catalog data (main star data)
        if verbose:
            print("  Creating catalog dataset...")
        dcpl_catalog = h5py.h5p.create(h5py.h5p.DATASET_CREATE)
        dcpl_catalog.set_chunk(chunk_shape)
        if compress and HAS_ZSTD:
            dcpl_catalog.set_filter(ZSTD_FILTER_ID, 0, (ZSTD_LEVEL,))
        
        # Create empty dataset - we'll fill it later
        catalog_ds = fout.create_dataset(
            'catalog',
            shape=(total_stars, num_columns),
            dtype=np.float64,
            dcpl=dcpl_catalog
        )
        
        # 4. Trixel mapping
        if verbose:
            print("  Writing trixel mapping...")
        fout.create_dataset('trixel_ids', data=np.array(trixel_ids, dtype=np.uint32))
        fout.create_dataset('trixel_offsets', data=offsets)
        
        # 5. Metadata attributes
        fout.attrs['catalog_name'] = catalog_name
        fout.attrs['num_trixels'] = len(trixel_ids)
        fout.attrs['num_columns'] = num_columns
        fout.attrs['total_stars'] = total_stars
        fout.attrs['chunk_shape'] = str(chunk_shape)
        fout.attrs['lookup_method'] = 'binary_search'
        fout.attrs['has_gaps'] = False
        if compress and HAS_ZSTD:
            fout.attrs['compression'] = 'zstd'
            fout.attrs['compression_level'] = ZSTD_LEVEL
        else:
            fout.attrs['compression'] = 'none'
    
    return offsets


def fill_catalog_data(
    output_path: str,
    trixel_files: List[str],
    trixel_ids: List[int],
    offsets: np.ndarray,
    num_columns: int,
    verbose: bool = False
) -> None:
    """
    Fill the catalog dataset with star data from trixel files.
    
    Args:
        output_path: Path to output HDF5 file
        trixel_files: List of trixel file paths
        trixel_ids: List of all trixel IDs (one per dataset)
        offsets: Pre-computed offset array
        num_columns: Number of columns
        verbose: Print progress
    """
    with h5py.File(output_path, 'r+') as fout:
        catalog_ds = fout['catalog']
        
        # Track position
        pos = 0
        trixel_idx = 0
        
        iterator = trixel_files
        if HAS_TQDM:
            iterator = tqdm(trixel_files, desc="Copying star data", unit="file")
        
        for tf in iterator:
            with h5py.File(tf, 'r') as fin:
                # Get all non-_Ind datasets
                dataset_names = [k for k in fin.keys() if not k.endswith('_Ind')]
                
                for name in dataset_names:
                    src = fin[name][:]  # (num_columns, star_count_in_this_dataset)
                    
                    # This dataset corresponds to trixel_ids[trixel_idx]
                    start = offsets[trixel_idx]
                    end = offsets[trixel_idx + 1]
                    expected_stars = end - start
                    
                    if src.shape[1] != expected_stars:
                        raise ValueError(
                            f"Star count mismatch for trixel {trixel_ids[trixel_idx]}: "
                            f"expected {expected_stars}, got {src.shape[1]}"
                        )
                    
                    # Transpose to (star_count, num_columns) and copy
                    catalog_ds[start:end, :] = np.transpose(src)
                    
                    trixel_idx += 1
                    pos = end
        
        if pos != offsets[-1]:
            raise ValueError(f"Final position mismatch: expected {offsets[-1]}, got {pos}")


def load_colcell_mat(colcell_path: str) -> Tuple[List[str], List[str]]:
    """
    Load ColCell and ColUnits from a .mat file.
    
    Args:
        colcell_path: Path to .mat file
        
    Returns:
        Tuple of (colcell, colunits) lists
    """
    mat_data = scipy.io.loadmat(colcell_path)
    
    # Extract ColCell and ColUnits
    colcell_raw = mat_data.get('ColCell', [[[]]])
    colunits_raw = mat_data.get('ColUnits', [[[]]])
    
    # Handle MATLAB cell array format
    if isinstance(colcell_raw, np.ndarray) and colcell_raw.ndim == 2:
        colcell = []
        for item in colcell_raw.flatten():
            if isinstance(item, np.ndarray) and item.size > 0:
                colcell.append(str(item[0]))
            else:
                colcell.append('')
    else:
        colcell = [str(x) for x in colcell_raw.flatten()]
    
    if isinstance(colunits_raw, np.ndarray) and colunits_raw.ndim == 2:
        colunits = []
        for item in colunits_raw.flatten():
            if isinstance(item, np.ndarray) and item.size > 0:
                colunits.append(str(item[0]))
            else:
                colunits.append('')
    else:
        colunits = [str(x) for x in colunits_raw.flatten()]
    
    return colcell, colunits


def main():
    """Main conversion routine."""
    args = parse_args()
    
    # Setup paths
    input_dir = Path(args.input_dir)
    output_path = Path(args.output)
    
    # Check inputs
    if not input_dir.exists():
        print(f"Error: Input directory does not exist: {input_dir}")
        sys.exit(1)
    
    if output_path.exists() and not args.overwrite:
        print(f"Error: Output file exists: {output_path}")
        print("Use --overwrite to replace it.")
        sys.exit(1)
    
    # Find files
    if args.verbose:
        print(f"Scanning {input_dir} for {args.catalog_name} files...")
    
    index_path, colcell_path, trixel_files = find_catalog_files(input_dir, args.catalog_name)
    
    if not index_path:
        print("Warning: Could not find index file. Will proceed without it.")
    if not colcell_path:
        print("Warning: Could not find ColCell file. Will proceed without column metadata.")
    if not trixel_files:
        print("Error: No trixel files found!")
        sys.exit(1)
    
    if args.verbose:
        print(f"  Index file: {index_path}")
        print(f"  ColCell file: {colcell_path}")
        print(f"  Trixel files: {len(trixel_files)}")
    
    # Load ColCell if available
    colcell = []
    colunits = []
    if colcell_path:
        try:
            colcell, colunits = load_colcell_mat(colcell_path)
            if args.verbose:
                print(f"  Loaded {len(colcell)} columns from ColCell")
        except Exception as e:
            print(f"Warning: Could not load ColCell: {e}")
    
    # Load index if available
    index_data = None
    if index_path:
        try:
            with h5py.File(index_path, 'r') as f:
                # Find the index dataset
                for name in f.keys():
                    if 'HTM' in name.upper() or 'index' in name.lower():
                        index_data = f[name][:]
                        break
                else:
                    # Take the first dataset that looks like an index
                    for name in f.keys():
                        obj = f[name]
                        if isinstance(obj, h5py.Dataset) and obj.ndim == 2:
                            index_data = obj[:]
                            break
            if args.verbose and index_data is not None:
                print(f"  Loaded index: shape={index_data.shape}")
        except Exception as e:
            print(f"Warning: Could not load index: {e}")
    
    # Count stars and gather info
    if args.verbose:
        print("\nAnalyzing trixel files...")
    
    total_stars, num_columns, trixel_ids, star_counts = count_total_stars(
        trixel_files, args.verbose
    )
    
    if args.verbose:
        print(f"  Total stars: {total_stars:,}")
        print(f"  Columns: {num_columns}")
        print(f"  Trixels: {len(trixel_ids)}")
        if trixel_ids:
            print(f"  Trixel range: {min(trixel_ids)} to {max(trixel_ids)}")
    
    # Create output file
    chunk_shape = (args.chunk_stars, args.chunk_cols)
    
    if args.verbose:
        print(f"\nCreating consolidated file...")
    
    offsets = create_consolidated_file(
        str(output_path),
        args.catalog_name,
        index_data,
        colcell,
        colunits,
        trixel_ids,
        star_counts,
        num_columns,
        total_stars,
        chunk_shape,
        args.compress,
        args.verbose
    )
    
    # Fill catalog data
    if args.verbose:
        print(f"\nFilling catalog data...")
    
    fill_catalog_data(
        str(output_path),
        trixel_files,
        trixel_ids,
        offsets,
        num_columns,
        args.verbose
    )
    
    # Report success
    file_size = output_path.stat().st_size
    size_mb = file_size / 1024 / 1024
    
    print(f"\n✅ Successfully converted to consolidated format!")
    print(f"   Output: {output_path}")
    print(f"   Size: {size_mb:.2f} MB")
    print(f"   Trixels: {len(trixel_ids)}")
    print(f"   Stars: {total_stars:,}")
    print(f"   Columns: {num_columns}")
    if args.compress and HAS_ZSTD:
        print(f"   Compression: zstd level {ZSTD_LEVEL}")
    else:
        print(f"   Compression: disabled")


if __name__ == "__main__":
    main()
