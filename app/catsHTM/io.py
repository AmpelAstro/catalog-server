"""I/O utilities for catsHTM catalogs.

Provides functions for loading HDF5 datasets and MATLAB (.mat) files,
both from local filesystem and S3 storage.
"""

import os
from functools import lru_cache

import h5py
import numpy as np
import structlog

from .params import ColCelFile, IndexFileTemplate

logger = structlog.get_logger(__name__)


def _is_s3_uri(path: str) -> bool:
    """
    Check if the given path is an S3 URI.

    Args:
        path: The path to check

    Returns:
        True if path starts with 's3://', False otherwise
    """
    return isinstance(path, str) and path.startswith("s3://")


def load_hdf5_dataset(file_path: str, dataset_name: str) -> np.ndarray:
    """
    Load a dataset from an HDF5 file.
    
    Supports both local filesystem paths and S3 URIs via HDF5 ROS3 VFD.
    
    Args:
        file_path: Path to the HDF5 file (can be s3:// URI)
        dataset_name: Name of the dataset to load
    
    Returns:
        numpy array containing the dataset data
    
    Raises:
        FileNotFoundError: If the file doesn't exist (local) or can't be opened (S3)
        KeyError: If the dataset doesn't exist in the file
        OSError: For other HDF5/S3 access errors
    """
    # Handle S3 URIs with ROS3 VFD
    if _is_s3_uri(file_path):
        logger.info("Opening S3 file", file_path=file_path)
        try:
            with h5py.File(file_path, "r", driver="ros3") as f:
                if dataset_name not in f:
                    logger.warning(
                        "Dataset not found in S3 file",
                        file_path=file_path,
                        dataset_name=dataset_name,
                    )
                    raise KeyError(
                        f"Dataset '{dataset_name}' not found in HDF5 file '{file_path}'"
                    )
                return np.array(f[dataset_name])
        except (OSError, ValueError) as e:
            logger.error(
                "Cannot open S3 file",
                file_path=file_path,
                error=str(e),
            )
            raise OSError(f"Cannot open S3 file <{file_path}>: {e}") from e
    else:
        # Local filesystem
        if not os.path.exists(file_path):
            logger.warning("File not found", file_path=file_path)
            raise FileNotFoundError(f"HDF5 file not found: {file_path}")
        
        with h5py.File(file_path, "r") as f:
            if dataset_name not in f:
                logger.warning(
                    "Dataset not found in file",
                    file_path=file_path,
                    dataset_name=dataset_name,
                )
                raise KeyError(
                    f"Dataset '{dataset_name}' not found in HDF5 file '{file_path}'"
                )
            return np.array(f[dataset_name])


@lru_cache(16)
def get_index_data(path: str, CatDir: str, Filename: str, VarName: str) -> np.ndarray:
    """
    Load index data from an HDF5 file with caching.
    
    Args:
        path: Root path to the catalog directory
        CatDir: Subdirectory for the catalog
        Filename: Name of the HDF5 file
        VarName: Name of the dataset/variable to load
    
    Returns:
        numpy array containing the index data
    """
    full_path = path.rstrip("/") + "/" + CatDir.lstrip("/") + "/" + Filename
    return load_hdf5_dataset(full_path, VarName)


def load_colcell(catalogs_dir: str, CatName: str) -> tuple[int, np.ndarray, np.ndarray]:
    """
    Load and process column cell data from a .mat file.
    
    Args:
        catalogs_dir: Root directory containing catalog data
        CatName: Name of the catalog
    
    Returns:
        Tuple of (Ncol, ColCell, ColUnits) where:
        - Ncol: Number of columns
        - ColCell: Processed column cell data as object array of strings
        - ColUnits: Processed column units as object array of strings
    
    Raises:
        FileNotFoundError: If the .mat file cannot be found or loaded
    """
    from ..matlab_utils import loadmat as sio_loadmat
    from scipy.io.matlab import MatReadError
    
    CatDir = get_CatDir(CatName)
    file_path = catalogs_dir.rstrip("/") + "/" + CatDir.lstrip("/") + "/" + (ColCelFile % CatName)
    
    # Use our S3-aware loadmat which handles both local and S3 URIs
    # For S3 URIs, os.path.isfile doesn't work, so we just try to load
    if os.path.isfile(file_path) or _is_s3_uri(file_path):
        try:
            mat_data = sio_loadmat(file_path)
        except (NotImplementedError, ValueError, MatReadError):
            logger.warning(
                "S3-aware loadmat failed, falling back to scipy",
                file_path=file_path,
            )
            from scipy.io import loadmat as scipy_loadmat
            mat_data = scipy_loadmat(file_path)
        
        # Determine Ncol based on ColCell shape
        if np.shape(mat_data["ColCell"])[1] < np.shape(mat_data["ColCell"])[0]:
            Ncol = np.shape(mat_data["ColCell"])[0]
        else:
            Ncol = np.shape(mat_data["ColCell"])[1]
        
        # Initialize output arrays
        ColCell = np.empty((Ncol), dtype=object)
        ColUnits = np.empty((Ncol), dtype=object)
        
        # Process ColCell and ColUnits based on orientation
        if np.shape(mat_data["ColCell"])[1] > np.shape(mat_data["ColCell"])[0]:
            # Wide format: ColCell[0, :]
            for i, j in enumerate(mat_data["ColCell"][0, :]):
                ColCell[i] = str(mat_data["ColCell"][0, i][0])
            for i, j in enumerate(mat_data["ColUnits"][0, :]):
                if len(mat_data["ColUnits"][0, i]) > 0:
                    ColUnits[i] = str(mat_data["ColUnits"][0, i][0])
                else:
                    ColUnits[i] = " "
        else:
            # Tall format: ColCell[:, 0] (rare cases: Cosmos and TMASSxsc)
            for i, j in enumerate(mat_data["ColCell"][:, 0]):
                ColCell[i] = str(mat_data["ColCell"][i][0][0])
            for i, j in enumerate(mat_data["ColUnits"][0, :]):
                if len(mat_data["ColUnits"][0, i]) > 0:
                    ColUnits[i] = str(mat_data["ColUnits"][0, i][0])
                else:
                    ColUnits[i] = " "
        
        return Ncol, ColCell, ColUnits
    else:
        raise FileNotFoundError(
            f"Cannot find ColCell file at {file_path}, "
            "you need to specify a valid path for the catalogs location"
        )


def get_CatDir(CatName: str) -> str:
    """
    Get the directory name for a catalog.
    
    Some catalogs have different directory names than their catalog names.
    
    Args:
        CatName: Name of the catalog
    
    Returns:
        Directory name for the catalog
    """
    if CatName == "TMASS":
        CatDir = "2MASS"
    elif CatName == "TMASSxsc":
        CatDir = "2MASSxsc"
    elif CatName == "DECaLS":
        CatDir = "DECaLS/DR5"
    elif CatName == "GAIADR1":
        CatDir = "GAIA/DR1"
    elif CatName == "GAIADR2":
        CatDir = "GAIA/DR2"
    elif CatName == "GAIAEDR3":
        CatDir = "GAIA/DRE3"
    elif CatName == "GALEX":
        CatDir = "GALEX/DR6Plus7"
    elif CatName == "HSCv2":
        CatDir = "HST/HSCv2"
    elif CatName == "IPHAS":
        CatDir = "IPHAS/DR2"
    elif CatName == "NEDz":
        CatDir = "NED/20180502"
    elif CatName == "SDSSDR10":
        CatDir = "SDSS/DR10"
    elif CatName == "SDSSoffset":
        CatDir = "SDSS/DR14offset"
    elif CatName == "SpecSDSS":
        CatDir = "SpecSDSS/DR14"
    elif CatName == "SAGE":
        CatDir = "Spitzer/SAGE"
    elif CatName == "IRACgc":
        CatDir = "Spitzer/IRACgc"
    elif CatName == "UKIDSS":
        CatDir = "UKIDSS/DR10"
    elif CatName == "VISTAviking":
        CatDir = "VISTA/Viking/DR2"
    elif CatName == "VSTatlas":
        CatDir = "VST/ATLAS/DR3"
    elif CatName == "VSTkids":
        CatDir = "VST/KiDS/DR3"
    elif CatName == "ztfSrcLCDR1":
        CatDir = "./ZTF/SrcLCDR1"
    elif CatName == "ztfDR1var":
        CatDir = "./ZTF/ztfDR1var"
    elif CatName not in [
        "AKARI",
        "APASS",
        "Cosmos",
        "FIRST",
        "NVSS",
        "PS1",
        "PTFpc",
        "PGC",
        "ROSATfsc",
        "SkyMapper",
        "UCAC4",
        "WISE",
        "XMM",
        "NOAO",
    ]:
        raise ValueError(
            "you need to specify a valid name for the catalog (see README file for list of available catalogs and names)"
        )
    else:
        CatDir = CatName
    return CatDir
