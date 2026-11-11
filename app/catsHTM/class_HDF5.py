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
******************************************************"""

import os

import h5py

# import pdb
import numpy as np


def _is_s3_uri(path: str) -> bool:
    """
    Check if the given path is an S3 URI.

    Args:
        path: The path to check

    Returns:
        True if path starts with 's3://', False otherwise
    """
    return isinstance(path, str) and path.startswith("s3://")


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
        filename = self.FileName

        # Handle S3 URIs with ROS3 VFD
        if _is_s3_uri(filename):
            # For S3 URIs, use ROS3 VFD driver
            if Verbose == True:
                print(f"Opening S3 file: {filename}")
            try:
                f = h5py.File(filename, "r", driver="ros3")
            except (OSError, ValueError) as e:
                if Verbose == True:
                    print(
                        f"Cannot open S3 file <{filename}>: {e}. "
                        "Ensure AWS_ENDPOINT_URL and credentials are configured."
                    )
                raise OSError(f"Cannot open S3 file <{filename}>: {e}") from e
        else:
            # Existing local filesystem logic
            if os.path.exists(filename) == False:
                if Verbose == True:
                    print(
                        f"Cannot open the file <{filename}>, it does not exist, the trixel must be empty of sources"
                    )
                raise FileNotFoundError(f"HDF5 file not found: {filename}")
            f = h5py.File(filename, "r")

        # Common processing for both S3 and local files
        if dataset_name not in f:
            if Verbose == True:
                print(
                    f"Cannot read Dataset <{dataset_name}> from hdf5 file <{f}>, the trixel must be empty of sources"
                )
            f.close()
            raise KeyError(f"Dataset '{dataset_name}' not found in HDF5 file '{filename}'")
        else:
            if numpy_array == True:
                datax = np.array(f[dataset_name])
                if Block is not None:
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
                    data = datax
            else:
                if Block is not None:
                    print("stop, Block not none unsupported")
                    data = f[dataset_name]
                else:
                    data = f[dataset_name]
                # MemSpaceId=h5py.h5s.create_simple(TUPLE dims_tpl, TUPLE max_dims_tpl)

        f.close()
        return data
