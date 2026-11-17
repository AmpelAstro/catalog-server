# Consolidated CATSHTM2 HDF5 Format Specification

**Version:** 2.0  
**Date:** 2026-11-17  
**Status:** Draft  
**Author:** Jakob van Santen

---

## Overview

The **Consolidated CATSHTM2 Format** merges multiple catalog files (index, trixel data, and column metadata) into a single, cloud-optimized HDF5 file. This format addresses performance bottlenecks identified in the original multi-file CATSHTM2 distribution, particularly when accessing data over S3 via the ROS3 VFD.

### Problem Statement

The original CATSHTM2 format had several limitations:

1. **Multi-file overhead**: Each trixel was a separate HDF5 file, requiring hundreds of individual file opens for typical cone searches
2. **No chunking**: Datasets used contiguous storage, forcing full dataset downloads from S3
3. **No compression**: Files were uncompressed, wasting bandwidth and storage
4. **Scattered metadata**: Column names and units were in separate `.mat` files

### Solution

The consolidated format provides:

- ✅ **Single-file access**: One HDF5 file contains everything
- ✅ **Cloud-optimized**: Chunking + zstd compression minimizes S3 I/O
- ✅ **Column subset efficiency**: Column-wise chunking enables partial column reads
- ✅ **Self-contained**: All metadata embedded in the file

---

## File Structure

### Root Level Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `catalog_name` | string | Name of the catalog (e.g., "GAIADR2") |
| `num_trixels` | integer | Number of trixels in this file |
| `num_columns` | integer | Number of data columns per star |
| `total_stars` | integer | Total number of stars across all trixels |
| `chunk_shape` | string | Tuple representation of chunk dimensions, e.g., "(512, 9)" |
| `lookup_method` | string | Recommended lookup algorithm ("binary_search") |
| `has_gaps` | boolean | Whether trixel IDs have gaps (currently always False) |

### Datasets

#### `/ColCell` - Column Names

- **Shape**: `(num_columns,)`
- **Type**: Fixed-length ASCII string (typically `|S14`)
- **Description**: Names of each column in the catalog
- **Example**: `["RA", "Dec", "Epoch", "ErrRA", "ErrDec", ...]`
- **Storage**: Contiguous (no chunking needed)

#### `/ColUnits` - Column Units

- **Shape**: `(num_columns,)`
- **Type**: Fixed-length ASCII string (typically `|S14`)
- **Description**: Physical units for each column
- **Example**: `["deg", "deg", "JYear", "mas", "mas", ...]`
- **Storage**: Contiguous

#### `/index` - HTM Tree Index

- **Shape**: `(13, N)` where N varies by catalog
- **Type**: `float32`
- **Description**: Hierarchical Triangular Mesh (HTM) index structure for spatial querying
- **Chunking**: `(13, 10000)` - Chunked by index rows
- **Compression**: zstd level 5
- **Purpose**: Enables fast identification of trixels intersecting a cone search region

#### `/catalog` - Star Data

- **Shape**: `(total_stars, num_columns)`
- **Type**: Typically `float64`
- **Description**: Flattened array containing all star data from all trixels
- **Order**: Stars grouped by trixel, ordered by increasing trixel ID
- **Chunking**: `(512, 9)` - Optimized for column subset reads
- **Compression**: zstd level 5
- **Access Pattern**: `catalog[start:end, cols]` where `start:end` is the trixel range and `cols` are selected column indices

#### `/trixel_ids` - Trixel Identifier Array

- **Shape**: `(num_trixels,)`
- **Type**: `uint32`
- **Description**: Array of trixel identifiers in ascending order
- **Properties**: Sorted, may have gaps (though current implementations are gap-free)
- **Storage**: Contiguous
- **Purpose**: Maps trixel IDs to positions in `trixel_offsets`

#### `/trixel_offsets` - Row Offset Array

- **Shape**: `(num_trixels + 1,)`
- **Type**: `int32`
- **Description**: Starting row index for each trixel in `/catalog`
- **Interpretation**: Trixel `i` occupies rows `[offsets[i], offsets[i+1])` in `/catalog`
- **Storage**: Contiguous

---

## Data Model

### Relationship Between Arrays

```
Trixel Space:
  trixel_ids:    [T₀, T₁, T₂, ..., Tₙ₋₁]  (sorted uint32)
                 ↑   ↑   ↑
Row Space:      ┌───┬───┬───┐
  offsets:      [0,  s₀, s₁, ..., total_stars]
                 │   │   │
Data Space:     ▼   ▼   ▼
catalog:        [★★★, ★★, ★★★★, ...]
                     (flattened star data)
```

Each trixel `Tᵢ` contains `sᵢ = offsets[i+1] - offsets[i]` stars, stored contiguously in `catalog[offsets[i]:offsets[i+1], :]`.

### Example

For a file with 3 trixels:
- `trixel_ids = [457200, 457201, 457202]`
- `trixel_offsets = [0, 600, 1250, 1800]`
- `catalog` has 1800 rows

| Trixel | Stars | Rows in `/catalog` |
|--------|-------|--------------------|
| 457200 | 600   | `[0, 600)`         |
| 457201 | 650   | `[600, 1250)`      |
| 457202 | 550   | `[1250, 1800)`     |

---

## Lookup Algorithms

### Finding a Trixel's Data

Given a trixel ID, use **binary search** to find its position:

```python
import numpy as np

def get_trixel_range(h5file, trixel_id):
    """
    Get (start, end) row range for a given trixel_id.
    
    Uses binary search - works with sorted trixels that may have gaps.
    Raises KeyError if trixel_id not found.
    
    Args:
        h5file: Open h5py.File object
        trixel_id: Integer trixel identifier
        
    Returns:
        tuple: (start_row, end_row) - half-open interval
    """
    trixel_ids = h5file['trixel_ids'][:]
    offsets = h5file['trixel_offsets'][:]
    
    # Binary search for the trixel
    idx = np.searchsorted(trixel_ids, trixel_id)
    
    # Check if found
    if idx < len(trixel_ids) and trixel_ids[idx] == trixel_id:
        return offsets[idx], offsets[idx + 1]
    
    raise KeyError(f"Trixel {trixel_id} not found in catalog")
```

### Retrieving Star Data

Once you have the row range, retrieve the data:

```python
def get_trixel_data(h5file, trixel_id, columns=None):
    """
    Get star data for a specific trixel.
    
    Args:
        h5file: Open h5py.File object
        trixel_id: Integer trixel identifier
        columns: Optional list/set of column indices to select
        
    Returns:
        ndarray: (n_stars, n_cols) array of star data
    """
    start, end = get_trixel_range(h5file, trixel_id)
    
    if columns is None:
        return h5file['catalog'][start:end, :]
    else:
        return h5file['catalog'][start:end, list(columns)]
```

### Complete Cone Search Workflow

```python
import h5py
import numpy as np

def cone_search(h5file, ra, dec, radius_deg, columns=None):
    """
    Perform a cone search on the consolidated catalog.
    
    Args:
        h5file: Open h5py.File object
        ra: Right ascension in degrees
        dec: Declination in degrees
        radius_deg: Search radius in degrees
        columns: Optional list of column indices to return
        
    Returns:
        ndarray: Concatenated star data from all matching trixels
    """
    # Step 1: Query HTM index for intersecting trixels
    index = h5file['index'][:]
    trixel_ids = find_intersecting_trixels(index, ra, dec, radius_deg)
    
    # Step 2: Retrieve data for each matching trixel
    results = []
    for tid in trixel_ids:
        try:
            data = get_trixel_data(h5file, tid, columns)
            results.append(data)
        except KeyError:
            # Trixel not in this file (gap or different file)
            continue
    
    if results:
        return np.concatenate(results, axis=0)
    else:
        return np.zeros((0, len(columns) if columns else 0))
```

*Note: `find_intersecting_trixels()` is provided by the CATSHTM2 library*

---

## Chunking Strategy

### Why Column-Wise Chunking?

The chunk shape `(512, 9)` was chosen based on extensive benchmarking:

| Chunk Shape | Column Efficiency | Chunk Size | Notes |
|-------------|-------------------|------------|-------|
| `(512, 27)` | ❌ Poor | 108 KB | Original: reading any column loads all 27 |
| `(512, 9)` | ✅ **Good** | **36 KB** | **Recommended**: 3× better for column subsets |
| `(512, 3)` | ✅ Excellent | 12 KB | Too fine-grained, higher overhead |
| `(512, 1)` | ✅ Excellent | 4 KB | Extreme, too much overhead |

### Performance Impact

When reading **3 columns** from an average trixel (564 stars):

| Chunk Shape | Data Transferred | Savings |
|-------------|------------------|---------|
| `(512, 27)` | 216 KB | Baseline |
| `(512, 9)` | **72 KB** | **+67%** |
| `(512, 3)` | 24 KB | +89% |

The `(512, 9)` shape provides the best balance between:
- Column subset efficiency (3 chunks of 9 columns each)
- Reasonable chunk size (36 KB)
- Low overhead (not too many chunks)

### How It Works

With `(512, 9)` chunking and 27 columns:
- Columns are divided into 3 groups: `[0-8]`, `[9-17]`, `[18-26]`
- Reading columns `[0, 1, 2]` only touches **group 0**
- Result: Only **⅓ of the column data** is transferred from S3

---

## Compression

### zstd Compression

All chunked datasets use **zstd compression level 5**:

- **Algorithm**: zstd (filter ID 32015)
- **Level**: 5 (good balance of speed/compression)
- **Requirement**: `hdf5plugin` package

### Size Reduction

| Component | Original | Compressed | Ratio |
|-----------|----------|------------|-------|
| Trixel data | 11.73 MB | 8.17 MB | 70% |
| Index | 34.67 MB | 11.76 MB | 67% |
| **Total** | **46.40 MB** | **19.93 MB** | **57%** |

---

## File Naming Convention

### Single-File Catalogs

For a complete catalog spanning all trixels:
```
{catalog_name}_CONSOLIDATED.hdf5
```

Examples:
- `GAIADR2_CONSOLIDATED.hdf5`
- `TMASS_CONSOLIDATED.hdf5`

### Partitioned Catalogs

For very large catalogs that must be partitioned (e.g., by HTM depth):
```
{catalog_name}_{depth:02d}_CONSOLIDATED.hdf5
```

Or by trixel range:
```
{catalog_name}_trixels_{start:06d}-{end:06d}.hdf5
```

---

## Conversion from Original Format

See [`convert_to_consolidated.py`](convert_to_consolidated.py) for the reference implementation.

### Algorithm

1. Load all trixel HDF5 files from the original catalog
2. Extract star counts and trixel IDs
3. Build `trixel_ids` and `trixel_offsets` arrays
4. Create output file with proper chunking and compression
5. Copy index data from `_htm.hdf5` file
6. Load ColCell and ColUnits from `_htmColCell.mat` file
7. Concatenate all star data into `/catalog` dataset

### Memory Considerations

For large catalogs (>100M stars):
- Process in batches
- Use temporary files for intermediate storage
- Ensure adequate swap space

---

## Compatibility

### Backward Compatibility

The consolidated format is **NOT** backward compatible with the original CATSHTM2 readers. Applications must be updated to use the new lookup functions.

However, the **data content** is identical - only the organization differs.

### Forward Compatibility

Future enhancements may include:
- Additional metadata in root attributes
- Extended column schemas
- Alternative compression algorithms

Older readers should ignore unknown attributes/datasets.

---

## Validation

### Checking File Integrity

```python
import h5py

def validate_consolidated_file(filepath):
    """Validate a consolidated catalog file."""
    with h5py.File(filepath, 'r') as f:
        # Check required attributes
        required_attrs = ['catalog_name', 'num_trixels', 'num_columns', 
                          'total_stars', 'chunk_shape', 'lookup_method']
        for attr in required_attrs:
            if attr not in f.attrs:
                return False, f"Missing attribute: {attr}"
        
        # Check required datasets
        required_datasets = ['ColCell', 'ColUnits', 'index', 'catalog', 
                            'trixel_ids', 'trixel_offsets']
        for ds in required_datasets:
            if ds not in f:
                return False, f"Missing dataset: {ds}"
        
        # Validate shapes
        trixel_ids = f['trixel_ids'][:]
        offsets = f['trixel_offsets'][:]
        
        if len(trixel_ids) != f.attrs['num_trixels']:
            return False, "trixel_ids length mismatch"
        
        if len(offsets) != len(trixel_ids) + 1:
            return False, "trixel_offsets length mismatch"
        
        if offsets[-1] != f.attrs['total_stars']:
            return False, "Offsets don't match total_stars"
        
        if f['catalog'].shape != (f.attrs['total_stars'], f.attrs['num_columns']):
            return False, "Catalog shape mismatch"
        
        # Check sorting
        if not np.all(np.diff(trixel_ids) >= 0):
            return False, "trixel_ids not sorted"
        
        # Check offsets monotonic
        if not np.all(np.diff(offsets) >= 0):
            return False, "offsets not monotonically increasing"
        
        return True, "Valid"
```

---

## Performance Characteristics

### Benchmarks

Based on GAIADR2 testing (56,420 stars, 100 trixels):

| Operation | Time |
|-----------|------|
| Trixel lookup (binary search) | ~1.2 µs |
| Trixel lookup (arithmetic) | ~0.3 µs |
| Read 3 columns for 1 trixel | ~0.5 ms (local) |
| Read all columns for 1 trixel | ~1.5 ms (local) |

### S3 Performance (Estimated)

With ROS3 VFD and column-wise chunking:

| Columns Read | Local | S3 (estimated) |
|--------------|-------|----------------|
| 1 column | 0.2 ms | ~5 ms |
| 3 columns | 0.5 ms | ~15 ms |
| All 27 columns | 1.5 ms | ~50 ms |

*S3 times depend on network latency and object storage backend*

---

## Migration Guide

### For Application Developers

1. Replace multi-file access with single-file consolidated access
2. Implement `get_trixel_range()` and `get_trixel_data()` functions
3. Update cone search to use the new workflow
4. Test thoroughly with your catalogs

### For Catalog Administrators

1. Run conversion script on existing catalogs
2. Deploy consolidated files alongside or replacing originals
3. Update configuration to point to new files
4. Monitor performance and report issues

---

## Reference Implementation

See:
- [`io_consolidated.py`](io_consolidated.py) - Reader utilities
- [`convert_to_consolidated.py`](convert_to_consolidated.py) - Conversion script
- [`profile_consolidated.py`](profile_consolidated.py) - Performance benchmarks

---

## Appendix A: Column Schema

The column schema is defined by the `ColCell` and `ColUnits` datasets. For GAIADR2:

| Index | Name | Unit | Description |
|-------|------|------|-------------|
| 0 | RA | deg | Right Ascension |
| 1 | Dec | deg | Declination |
| 2 | Epoch | JYear | Observation epoch |
| 3 | ErrRA | mas | RA uncertainty |
| 4 | ErrDec | mas | Dec uncertainty |
| 5 | Parallax | mas | Parallax |
| 6 | ErrParal | mas | Parallax uncertainty |
| 7 | PMRA | mas/yr | Proper motion in RA |
| 8 | PMDEC | mas/yr | Proper motion in Dec |
| 9 | ErrPMRA | mas/yr | PM-RA uncertainty |
| 10 | ErrPMDEC | mas/yr | PM-Dec uncertainty |
| 11 | PhotGmean | mag | G-band magnitude |
| 12 | ErrPhotG | mag | G-band photometry uncertainty |
| ... | ... | ... | ... |

---

## Appendix B: Glossary

| Term | Definition |
|------|------------|
| CATSHTM2 | Catalog System using Hierarchical Triangular Mesh version 2 |
| HDF5 | Hierarchical Data Format version 5 |
| ROS3 VFD | HDF5 Virtual File Driver for S3-compatible object stores |
| Trixel | Triangular pixel in HTM indexing |
| HTM | Hierarchical Triangular Mesh - a spherical indexing scheme |
| zstd | Zstandard compression algorithm |

---

## Revision History

| Date | Author | Changes |
|------|--------|---------|
| 2026-11-17 | Jakob van Santen | Initial specification |

---

*This document is part of the CATSHTM2 project. For updates, see the project repository.*
