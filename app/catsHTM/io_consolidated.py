# type: ignore
"""
IO Module for Consolidated CATSHTM2 HDF5 Files

This module provides utilities for reading the consolidated HDF5 format
that merges index, trixel data, and metadata into a single file.

See CONSOLIDATED_FORMAT_SPEC.md for the complete format specification.

Note: This module uses type: ignore comments extensively due to
complexities with h5py type annotations that pyright struggles with.
The code is tested and works correctly despite the type checker warnings.
"""

import h5py
import numpy as np
from typing import Optional, Union, List, Tuple
from pathlib import Path


class ConsolidatedCatalog:
    """
    Reader for consolidated CATSHTM2 HDF5 catalogs.
    
    Provides efficient access to star data with support for:
    - Binary search lookup of trixels (handles gaps)
    - Column subset selection
    - Lazy loading of datasets
    
    Example usage:
        >>> cat = ConsolidatedCatalog("GAIADR2_CONSOLIDATED.hdf5")
        >>> data = cat.get_trixel_data(457200, columns=[0, 1, 2])
        >>> ra, dec = data[:, 0], data[:, 1]
    """
    
    def __init__(self, filepath: Union[str, Path]):
        """
        Initialize the catalog reader.
        
        Args:
            filepath: Path to the consolidated HDF5 file
        """
        self.filepath = Path(filepath)
        self._file = None
        self._trixel_ids = None
        self._trixel_offsets = None
        self._colcell = None
        self._colunits = None
        self._metadata = None
    
    def __enter__(self):
        """Open the file for context manager usage."""
        self.open()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close the file when exiting context."""
        self.close()
        return False
    
    def open(self):
        """Open the HDF5 file and load metadata."""
        if self._file is not None:
            return
        
        self._file = h5py.File(str(self.filepath), 'r')
        self._load_metadata()
    
    def close(self):
        """Close the HDF5 file and clear cached data."""
        if self._file is not None:
            self._file.close()
            self._file = None
        self._trixel_ids = None
        self._trixel_offsets = None
        self._colcell = None
        self._colunits = None
        self._metadata = None
    
    def _load_metadata(self):
        """Load metadata from the open file."""
        if self._file is None:
            raise RuntimeError("File not open. Call open() first.")
        
        # Load attributes
        self._metadata = {k: v for k, v in self._file.attrs.items()}
        
        # Load trixel mapping (cached for performance)
        self._trixel_ids = np.asarray(self._file['trixel_ids'])
        self._trixel_offsets = np.asarray(self._file['trixel_offsets'])
        self._colcell = np.asarray(self._file['ColCell'])
        self._colunits = np.asarray(self._file['ColUnits'])
    
    @property
    def is_open(self) -> bool:
        """Check if the file is currently open."""
        return self._file is not None
    
    @property
    def catalog_name(self) -> str:
        """Name of the catalog."""
        if self._metadata is None:
            self._load_metadata()
        return self._metadata.get('catalog_name', 'Unknown')  # type: ignore
    
    @property
    def num_trixels(self) -> int:
        """Number of trixels in the catalog."""
        if self._metadata is None:
            self._load_metadata()
        return self._metadata.get('num_trixels', 0)  # type: ignore
    
    @property
    def num_columns(self) -> int:
        """Number of columns per star."""
        if self._metadata is None:
            self._load_metadata()
        return self._metadata.get('num_columns', 0)  # type: ignore
    
    @property
    def total_stars(self) -> int:
        """Total number of stars in the catalog."""
        if self._metadata is None:
            self._load_metadata()
        return self._metadata.get('total_stars', 0)  # type: ignore
    
    @property
    def colnames(self) -> List[str]:
        """List of column names."""
        if self._colcell is None:
            self._load_metadata()
        # Decode bytes to strings if needed
        result = []
        for c in self._colcell:
            if isinstance(c, bytes):
                result.append(c.decode('utf-8'))
            else:
                result.append(str(c))
        return result
    
    @property
    def colunits(self) -> List[str]:
        """List of column units."""
        if self._colunits is None:
            self._load_metadata()
        # Decode bytes to strings if needed
        result = []
        for u in self._colunits:
            if isinstance(u, bytes):
                result.append(u.decode('utf-8'))
            else:
                result.append(str(u))
        return result
    
    @property
    def trixel_ids(self) -> np.ndarray:
        """Array of all trixel IDs in the catalog."""
        if self._trixel_ids is None:
            self._load_metadata()
        return self._trixel_ids.copy()
    
    def get_col_index(self, colname: str) -> int:
        """
        Get the index of a column by name.
        
        Args:
            colname: Column name (case-sensitive)
            
        Returns:
            Column index
            
        Raises:
            KeyError: If column name not found
        """
        for i, name in enumerate(self.colnames):
            if name == colname:
                return i
        raise KeyError(f"Column '{colname}' not found. Available: {self.colnames}")
    
    def get_trixel_range(self, trixel_id: int) -> Tuple[int, int]:
        """
        Get the row range for a given trixel ID.
        
        Uses binary search - works with sorted trixels that may have gaps.
        
        Args:
            trixel_id: Integer trixel identifier
            
        Returns:
            Tuple of (start_row, end_row) - half-open interval [start, end)
            
        Raises:
            KeyError: If trixel_id not found in catalog
            RuntimeError: If file is not open
        """
        if self._file is None:
            raise RuntimeError("File not open. Call open() first.")
        
        if self._trixel_ids is None:
            self._load_metadata()
        
        # Binary search for the trixel
        idx = np.searchsorted(self._trixel_ids, trixel_id)
        
        # Check if found
        if idx < len(self._trixel_ids) and self._trixel_ids[idx] == trixel_id:
            return int(self._trixel_offsets[idx]), int(self._trixel_offsets[idx + 1])
        
        raise KeyError(f"Trixel {trixel_id} not found in catalog")
    
    def get_trixel_data(
        self, 
        trixel_id: int, 
        columns: Optional[Union[List[int], np.ndarray]] = None
    ) -> np.ndarray:
        """
        Get star data for a specific trixel.
        
        Args:
            trixel_id: Integer trixel identifier
            columns: Optional list of column indices to select.
                     If None, returns all columns.
        
        Returns:
            ndarray: (n_stars, n_cols) array of star data
            
        Raises:
            KeyError: If trixel_id not found
            RuntimeError: If file is not open
        """
        if self._file is None:
            raise RuntimeError("File not open. Call open() first.")
        
        start, end = self.get_trixel_range(trixel_id)
        
        if columns is None:
            return self._file['catalog'][start:end, :]
        else:
            return self._file['catalog'][start:end, list(columns)]
    
    def get_trixel_data_by_name(
        self,
        trixel_id: int,
        colnames: Optional[Union[List[str], str]] = None
    ) -> np.ndarray:
        """
        Get star data for a specific trixel, specified by column names.
        
        Args:
            trixel_id: Integer trixel identifier
            colnames: Optional column name(s) to select.
                      If string, selects single column.
                      If list, selects multiple columns.
                      If None, returns all columns.
        
        Returns:
            ndarray: (n_stars, n_cols) array of star data
        """
        if colnames is None:
            return self.get_trixel_data(trixel_id)
        elif isinstance(colnames, str):
            return self.get_trixel_data(trixel_id, [self.get_col_index(colnames)])
        else:
            indices = [self.get_col_index(name) for name in colnames]
            return self.get_trixel_data(trixel_id, indices)
    
    def get_index_data(self) -> np.ndarray:
        """
        Get the HTM index data.
        
        Returns:
            ndarray: (13, N) HTM tree index
        """
        if self._file is None:
            raise RuntimeError("File not open. Call open() first.")
        return self._file['index'][:]
    
    def cone_search(
        self,
        ra: float,
        dec: float,
        radius_deg: float,
        columns: Optional[Union[List[int], List[str]]] = None
    ) -> np.ndarray:
        """
        Perform a cone search on the catalog.
        
        Note: This is a placeholder. The actual HTM index query
        depends on the CATSHTM2 implementation.
        
        Args:
            ra: Right ascension in degrees
            dec: Declination in degrees
            radius_deg: Search radius in degrees
            columns: Optional column indices or names to return
        
        Returns:
            ndarray: Concatenated star data from all matching trixels
        """
        # Placeholder - implement using CATSHTM2 HTM query
        # For now, just return data from first trixel as example
        first_trixel = self.trixel_ids[0]
        return self.get_trixel_data(first_trixel, columns)


def get_trixel_range(filepath: Union[str, Path], trixel_id: int) -> Tuple[int, int]:
    """
    Standalone function to get trixel range from a consolidated file.
    
    Args:
        filepath: Path to consolidated HDF5 file
        trixel_id: Integer trixel identifier
        
    Returns:
        Tuple of (start_row, end_row)
        
    Raises:
        KeyError: If trixel_id not found
    """
    with h5py.File(str(filepath), 'r') as f:
        trixel_ids = f['trixel_ids'][:]
        offsets = f['trixel_offsets'][:]
        
        idx = np.searchsorted(trixel_ids, trixel_id)
        if idx < len(trixel_ids) and trixel_ids[idx] == trixel_id:
            return int(offsets[idx]), int(offsets[idx + 1])
        
        raise KeyError(f"Trixel {trixel_id} not found in {filepath}")


def get_trixel_data(
    filepath: Union[str, Path],
    trixel_id: int,
    columns: Optional[List[int]] = None
) -> np.ndarray:
    """
    Standalone function to get trixel data from a consolidated file.
    
    Args:
        filepath: Path to consolidated HDF5 file
        trixel_id: Integer trixel identifier
        columns: Optional list of column indices
        
    Returns:
        ndarray: Star data for the trixel
    """
    with h5py.File(str(filepath), 'r') as f:
        start, end = get_trixel_range(filepath, trixel_id)
        if columns is None:
            return f['catalog'][start:end, :]
        else:
            return f['catalog'][start:end, list(columns)]


def validate_consolidated_file(filepath: Union[str, Path]) -> Tuple[bool, str]:
    """
    Validate a consolidated catalog file.
    
    Checks:
    - Required attributes exist
    - Required datasets exist
    - Shapes are consistent
    - Arrays are properly sorted
    
    Args:
        filepath: Path to the HDF5 file
        
    Returns:
        Tuple of (is_valid, message)
    """
    try:
        with h5py.File(str(filepath), 'r') as f:
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
            
            expected_shape = (f.attrs['total_stars'], f.attrs['num_columns'])
            if f['catalog'].shape != expected_shape:
                return False, f"Catalog shape mismatch: expected {expected_shape}, got {f['catalog'].shape}"
            
            # Check sorting
            if len(trixel_ids) > 0 and not np.all(np.diff(trixel_ids) >= 0):
                return False, "trixel_ids not sorted"
            
            # Check offsets monotonic
            if len(offsets) > 0 and not np.all(np.diff(offsets) >= 0):
                return False, "offsets not monotonically increasing"
            
            return True, "Valid"
    
    except Exception as e:
        return False, f"Validation error: {str(e)}"
