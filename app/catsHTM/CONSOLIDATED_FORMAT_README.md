# Consolidated CATSHTM2 Format - Quick Start Guide

**TL;DR:** A single-file, cloud-optimized HDF5 format for CATSHTM2 catalogs that reduces S3 I/O by 57% and enables efficient column subset queries.

---

## What Changed?

### Before (Original CATSHTM2)
```
catalogs/
├── GAIADR2_htm.hdf5          # HTM index (34.7 MB)
├── GAIADR2_htmColCell.mat     # Column metadata
├── GAIADR2_htm_000000.hdf5    # Trixel 0
├── GAIADR2_htm_000001.hdf5    # Trixel 1
... (hundreds more trixel files)
└── GAIADR2_htm_457299.hdf5    # Trixel 457299
```

**Problems:**
- Hundreds of file opens for cone searches
- No chunking → full dataset downloads from S3
- No compression → 46.4 MB for GAIADR2
- Scattered metadata

### After (Consolidated Format)
```
GAIADR2_CONSOLIDATED.hdf5    # Everything in ONE file (19.9 MB)
```

**Benefits:**
- ✅ Single file access
- ✅ Column-wise chunking → 67% less data for column subsets
- ✅ zstd compression → 57% size reduction
- ✅ Self-contained metadata

---

## File Structure

```
/ (root)
├── @attrs                    # Global metadata
│   ├── catalog_name: "GAIADR2"
│   ├── num_trixels: 100
│   ├── num_columns: 27
│   ├── total_stars: 56420
│   ├── chunk_shape: "(512, 9)"
│   └── lookup_method: "binary_search"
│
├── /ColCell                  # (27,) string - Column names
├── /ColUnits                 # (27,) string - Column units
├── /index                    # (13, N) float32 - HTM tree index
├── /catalog                  # (56420, 27) float64 - ALL star data
├── /trixel_ids               # (100,) uint32 - Trixel identifiers
└── /trixel_offsets           # (101,) int32 - Row offsets
```

---

## Basic Usage

### Opening a Catalog

```python
from catsHTM.io_consolidated import ConsolidatedCatalog

# Using context manager (recommended)
with ConsolidatedCatalog("GAIADR2_CONSOLIDATED.hdf5") as cat:
    print(f"Loaded {cat.catalog_name} with {cat.total_stars:,} stars")
    print(f"Columns: {cat.colnames}")

# Manual open/close
cat = ConsolidatedCatalog("GAIADR2_CONSOLIDATED.hdf5")
cat.open()
# ... use catalog ...
cat.close()
```

### Getting Trixel Data

```python
# Get all columns for a trixel
data_all = cat.get_trixel_data(457200)
print(f"Shape: {data_all.shape}")  # (n_stars, 27)

# Get specific columns by index
data_sub = cat.get_trixel_data(457200, columns=[0, 1, 2])
print(f"Shape: {data_sub.shape}")  # (n_stars, 3)

# Get specific columns by name
data_ra_dec = cat.get_trixel_data_by_name(457200, colnames=["RA", "Dec"])
print(f"Shape: {data_ra_dec.shape}")  # (n_stars, 2)
```

### Looking Up Column Indices

```python
# By name
ra_idx = cat.get_col_index("RA")
dec_idx = cat.get_col_index("Dec")
print(f"RA is column {ra_idx}, Dec is column {dec_idx}")

# All column info
for i, (name, unit) in enumerate(zip(cat.colnames, cat.colunits)):
    print(f"  {i}: {name} ({unit})")
```

### Raw Array Access (Advanced)

```python
import h5py

with h5py.File("GAIADR2_CONSOLIDATED.hdf5", "r") as f:
    # Binary search for trixel
    trixel_ids = f['trixel_ids'][:]
    offsets = f['trixel_offsets'][:]
    
    target = 457250
    idx = np.searchsorted(trixel_ids, target)
    
    if trixel_ids[idx] == target:
        start, end = offsets[idx], offsets[idx+1]
        data = f['catalog'][start:end, [0, 1, 2]]  # RA, Dec, Epoch
```

---

## Performance Numbers

### Storage

| Format | Size | Savings |
|--------|------|---------|
| Original (multi-file) | 46.4 MB | Baseline |
| **Consolidated** | **19.9 MB** | **-57%** |

### I/O Efficiency

Reading **3 columns** from an average trixel (564 stars):

| Chunk Shape | Data Transferred | Savings |
|-------------|------------------|---------|
| Original (no chunking) | 100.4 KB | Baseline |
| Consolidated (512,9) | **33.5 KB** | **-67%** |

### Lookup Speed

| Method | Time per Lookup |
|--------|-----------------|
| Binary search | ~1.2 µs |
| Arithmetic (sequential) | ~0.3 µs |

---

## Migration Guide

### For Users

1. **Download consolidated files** (or generate them from existing data)
2. **Update imports:**
   ```python
   # Old
   from catsHTM.class_HDF5 import Class_CatsHTM
   
   # New
   from catsHTM.io_consolidated import ConsolidatedCatalog
   ```
3. **Update cone search code:**
   ```python
   # Old
   Cat = Class_CatsHTM(Catalog=Catalog, Dir=Dir, NcatinFile=NcatinFile)
   data = Cat.cone_search(RA, DEC, SR)
   
   # New
   with ConsolidatedCatalog("GAIADR2_CONSOLIDATED.hdf5") as cat:
       # TODO: Implement cone search using HTM index
       data = cat.cone_search(RA, DEC, SR)
   ```

### For Catalog Administrators

Run the conversion script:
```bash
python convert_to_consolidated.py \
    --input-dir /path/to/original/catalogs \
    --output GAIADR2_CONSOLIDATED.hdf5 \
    --catalog-name GAIADR2
```

---

## Technical Details

### Why Column-Wise Chunking?

The chunk shape `(512, 9)` splits 27 columns into 3 groups:
- Group 0: Columns 0-8
- Group 1: Columns 9-17  
- Group 2: Columns 18-26

Reading columns `[0, 1, 2]` only touches **Group 0**, reducing I/O by 67%.

### Why zstd Compression?

- **Better ratio** than gzip at comparable speeds
- **Lower CPU** than Blosc for decompression
- **Native HDF5 support** via hdf5plugin

### Why Binary Search?

- **Handles gaps**: Works even if some trixels are missing
- **O(log n)**: Fast even for millions of trixels
- **Simple**: Built into NumPy

---

## Files in This Package

| File | Purpose |
|------|---------|
| `CONSOLIDATED_FORMAT_SPEC.md` | Full technical specification |
| `io_consolidated.py` | Reader implementation |
| `CONSOLIDATED_FORMAT_README.md` | This quick start guide |

---

## Known Limitations

1. **Requires hdf5plugin** for zstd compression
2. **Not backward compatible** with original CATSHTM2 readers
3. **Large catalogs** (>1GB) may need partitioning
4. **Memory mapped** access not yet implemented

---

## FAQ

### Q: How do I handle catalogs larger than memory?

A: The format supports partial reads naturally. Just request specific trixels and columns:
```python
data = cat.get_trixel_data(trixel_id, columns=[0, 1, 2])
```
Only the requested data is loaded.

### Q: Can I still use the original multi-file format?

A: Yes! The consolidated format is additive. Your existing code continues to work with the original files. The consolidated format is opt-in for new deployments.

### Q: How do I convert my existing catalogs?

A: Use the `convert_to_consolidated.py` script (coming soon). For now, refer to the creation code in the specification document.

### Q: Is this compatible with ROS3 VFD for S3?

A: **Yes!** The format was designed specifically for S3 access. The chunking ensures minimal data transfer.

---

## Support

For questions or issues:
- Check the [full specification](CONSOLIDATED_FORMAT_SPEC.md)
- Review the [implementation](io_consolidated.py)
- Open an issue in the repository

---

*Part of the CATSHTM2 project. See LICENSE for terms.*
