"""*******************************************************
A class that allows to access the variables in HDF5 files datasets by index of the elements in the array.
The class also include some basic tools to save and read HDF5 files.

Supports both local filesystem paths and S3 URIs via HDF5 ROS3 VFD.

Input  : null
Output : null
Tested :
By : Maayane T. Soumagnac                    February 2018
URL :
Reliable:


called this way from HDF5 import HDF5
*******************************************************"""

import os

import h5py

# import pdb
import numpy as np

import structlog

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
    if isinstance(file_path, str) and file_path.startswith("s3://"):
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


class HDF5:
    def __init__(self, FileName):  # ,VarName):
        self.FileName = FileName
        # self.VarName=VarName

    def load(
        self, dataset_name, numpy_array=False, Offset=None, Block=None, Verbose=True
    ):
        """Description: load an array from a HDF5
        Input:
            -HDF5 file name
            -Dataset name
            -numpy_array: if true, the output is given as a numpy array. Otherwise, it is given as in a HDF5 dataset format
            -[I,J] offset in the array from which to start uploading (?) If not given than get the entire array.
            -[I,J] block size to upload from array.
        Output : - a numpy array
        Example: class_HDF5.HDF5('FIRST_htm_010900.hdf5').load('htm_010921',numpy_array=True,Offset=[0,0],Block=[2,4])
        gives the transpose of Cat = HDF5.load('FIRST_htm_010900.hdf5','htm_010921',[1,1],[2,4]) in matlab"""
        # Legacy wrapper - delegates to the new function
        if numpy_array:
            return load_hdf5_dataset(self.FileName, dataset_name)
        else:
            # Non-numpy-array case not supported by new function
            # Fall back to old implementation for backwards compatibility
            filename = self.FileName

            if isinstance(filename, str) and filename.startswith("s3://"):
                if Verbose:
                    print(f"Opening S3 file: {filename}")
                try:
                    f = h5py.File(filename, "r", driver="ros3")
                except (OSError, ValueError) as e:
                    if Verbose:
                        print(
                            f"Cannot open S3 file <{filename}>: {e}. "
                            "Ensure AWS_ENDPOINT_URL and credentials are configured."
                        )
                    raise OSError(f"Cannot open S3 file <{filename}>: {e}") from e
            else:
                if not os.path.exists(filename):
                    if Verbose:
                        print(
                            f"Cannot open the file <{filename}>, it does not exist, the trixel must be empty of sources"
                        )
                    raise FileNotFoundError(f"HDF5 file not found: {filename}")
                f = h5py.File(filename, "r")

            if dataset_name not in f:
                if Verbose:
                    print(
                        f"Cannot read Dataset <{dataset_name}> from hdf5 file <{f}>, the trixel must be empty of sources"
                    )
                f.close()
                raise KeyError(f"Dataset '{dataset_name}' not found in HDF5 file '{filename}'")
            else:
                if Block is not None:
                    datax = np.array(f[dataset_name])
                    datay = datax.T
                    if Offset[0] - int(Offset[0]) > 0:
                        print(
                            "*********** Warning!!! Offset[0] is not an integer! ***********"
                        )
                    if Offset[1] - int(Offset[1]) > 0:
                        print(
                            "*********** Warning!!! Offset[1] is not an integer! ***********"
                        )
                    if Block[0] - int(Block[0]) > 0:
                        print(
                            "*********** Warning!!! Block[0] is not an integer! ***********"
                        )
                    if Block[1] - int(Block[1]) > 0:
                        print(
                            "*********** Warning!!! Block[1] is not an integer! ***********"
                        )
                    dataz = datay[
                        int(Offset[0]) : int(Offset[0]) + int(Block[0]),
                        int(Offset[1]) : int(Offset[1]) + int(Block[1]),
                    ]
                    data = dataz.T
                else:
                    data = np.array(f[dataset_name])
                f.close()
                return data
