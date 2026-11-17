# CATSHTM Performance Notes

## Overview

This document describes the data flow and performance characteristics of the CATSHTM cone search implementation, particularly when using S3-backed storage via HDF5 ROS3 VFD.

**See also:** [`HDF5_METADATA_ANALYSIS.md`](HDF5_METADATA_ANALYSIS.md) for deep dive on metadata storage and optimization opportunities.

## Data Flow

### Query Execution Flow

1. **Index Lookup** (`search_htm_ind` → `htm_search_cone`)
   - Loads `GAIADR2_HTM` dataset from index file (e.g., `GAIADR2_htm.hdf5`)
   - Recursively traverses HTM tree to find intersecting trixels
   - Returns list of winning leaf trixel IDs
   - **Cached**: `get_index_data()` uses `@lru_cache(16)` - index file loaded once per process

2. **Data Retrieval** (`cone_search`)
   - Groups leaf IDs into file batches (100 trixels per file by default, `NcatinFile=100.0`)
   - For each batch, loads corresponding HDF5 file (e.g., `GAIADR2_htm_174700.hdf5`)
   - Extracts specific dataset (e.g., `htm_174700`) from each file
   - **NOT CACHED**: Each `load_hdf5_dataset()` call hits S3 fresh

3. **Distance Filtering**
   - Stacks data from all files vertically
   - Computes spherical distances from cone center
   - Filters to `D < Radius`
   - Returns filtered catalog subset

### File Layout

#### Index Files (e.g., `GAIADR2_htm.hdf5`)
- Contains: Single dataset `GAIADR2_HTM` (shape: 13 × 699,048 float32)
- Size: ~34.67 MB
- Purpose: HTM tree structure for spatial indexing
- **Status**: ✅ Cached, loaded once per process

#### Data Files (e.g., `GAIADR2_htm_174700.hdf5`)
- Contains: Multiple datasets
  - `htm_XXXXXX`: Actual catalog data (shape varies, e.g., 27 × 175 float64)
  - `htm_XXXXXX_Ind`: Index/metadata arrays (shape: 2 × N, float64)
- Size: ~33-48 KB per dataset
- Purpose: Stores sources for specific trixel ranges
- **Status**: ❌ NOT cached, loaded fresh for each query

#### Unused Data
- `htm_XXXXXX_Ind` datasets: Contain column indices and weights, but **are never loaded or used** by the current implementation

## Performance Characteristics

### Benchmarks (S3-backed, Nov 2026)

| Radius | Objects Found | Avg Time | Dominant Cost |
|--------|---------------|----------|----------------|
| 100 arcsec | 5 | ~2.88s | Data file I/O |
| 1.5 arcsec | 0 | ~2.81s | Data file I/O |

**Key Finding**: Query radius has negligible impact on execution time because:
1. Same HTM trixels are checked regardless of small radius changes
2. Same data files are loaded before distance filtering
3. Distance filter runs on already-loaded data (fast numpy ops)

### Breakdown (Typical Query)

| Phase | Time | Notes |
|-------|------|-------|
| Index file load | ~0.5s | One-time cost, cached subsequently |
| 4× Data file loads | ~2.3s | Uncached, dominates total time |
| Tree traversal | <0.1s | Fast numpy operations |
| Distance filtering | <0.1s | Vectorized numpy |

### Cloud Optimization Assessment

Based on [Cloud Native Geo recommendations](https://guide.cloudnativegeo.org/cloud-optimized-netcdf4-hdf5/):

| Requirement | Status | Impact |
|-------------|--------|--------|
| Use chunking | ❌ NO | Full dataset downloads |
| Chunk size 1-10 MB | ❌ N/A | No chunking exists |
| Use compression | ❌ NO | Bandwidth wasted |
| External metadata | ❌ Likely not | Standard HDF5 layout |

**Critical Issue**: All datasets use **contiguous storage** (no chunking). This means:
- Every `load_hdf5_dataset()` call downloads the **entire dataset/file**
- Partial reads are impossible
- Network transfer dominates performance

### Specific Problems

1. **Index File** (`GAIADR2_HTM`): 34.67 MB, contiguous
   - Loaded once per process (cached)
   - Still wastes bandwidth on first query

2. **Data Files**: Multiple small contiguous datasets
   - Each `htm_XXXXXX` dataset: 33-48 KB
   - Entire file must be transferred for each dataset access
   - No opportunity for partial/range reads

## Implications

### Current Behavior
- **First query in process**: Pays full cost (~2.8s)
- **Subsequent queries**: Still ~2.8s because data files aren't cached
- **Different catalogs**: Each has its own index file (cached separately)

### Potential Optimizations

1. **Add LRU cache to `load_hdf5_dataset()`**
   ```python
   @lru_cache(maxsize=128)  # Adjust based on typical workload
   def load_hdf5_dataset(file_path: str, dataset_name: str) -> np.ndarray:
       ...
   ```
   - Would cache frequently-accessed data files
   - Risk: Memory usage grows with cache size

2. **Rechunk HDF5 files** (Requires offline processing)
   - Target chunk size: 4-8 MB
   - Use gzip/zstd compression
   - Enable partial reads via ROS3 VFD
   - Estimated improvement: 5-10× faster for repeated accesses

3. **Pre-filter by trixel**
   - Modify `cone_search` to filter by trixel before loading data
   - Reduces number of data files loaded
   - Complex: Requires metadata about which trixels have sources

## Recommendations

### Short-term (Easy Wins)
1. ✅ **Cache data files**: Add `@lru_cache` to `load_hdf5_dataset()`
2. ✅ **Reduce NcatinFile**: Smaller batches = finer-grained caching
3. ⚠️ **Local caching proxy**: Run squid/nginx cache in front of S3

### Medium-term (Infrastructure Changes)
1. 🔧 **Rechunk existing files**: Offline conversion to cloud-optimized format
2. 🔧 **Add compression**: gzip level 4-6 for good balance
3. 🔧 **Switch to Zarr/Parquet**: Better cloud-native support than HDF5

### Long-term (Architectural Changes)
1. 💡 **Spatial partitioning**: Pre-shard by declination bands
2. 💡 **Columnar storage**: Separate coordinates from photometry
3. 💡 **Materialized views**: Pre-compute common query patterns

## Testing Notes

When benchmarking:
- Use `--compare` flag in `profile_cone_search.py` to compare radii
- Remember: Index file is cached, data files are not
- Different processes = cold cache for everything
- Same process = index cached, data files still loaded fresh

## References

- [Cloud Native Geo Guide](https://guide.cloudnativegeo.org/cloud-optimized-netcdf4-hdf5/)
- [HDF5 ROS3 VFD Documentation](https://portal.hdfgroup.org/display/HDF5/ROSS3+-+Read+Only+S3+Virtual+File+Driver)
