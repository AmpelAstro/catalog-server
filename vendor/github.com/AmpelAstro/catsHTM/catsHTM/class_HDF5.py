"""*******************************************************
A class that allows to access the variables in HDF5 files datasets by index of the elements in the array.
The class also include some basic tools to save and read HDF5 files.

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


class HDF5:
    def __init__(self, FileName):  # ,VarName):
        self.FileName = FileName
        # self.VarName=VarName

    def info(self):
        """Description: goves info on the HDF5 file
        Input:

        Output :"""
        filename = self.FileName
        f = h5py.File(filename, "r")
        print(f"Filename:{filename}")
        print(
            f"Number of datasets in the HDF5 file {self.FileName}: {np.shape(list(f.keys()))}"
        )
        print(f"{np.shape(list(f.keys()))[0] / 2.0} pairs of [data file, indexfile]")
        print("****")
        print("The keys are:")
        print(list(f.keys()))
        print("****")

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
        if os.path.exists(filename) == False:
            if Verbose == True:
                print(
                    f"Cannot open the file <{filename}>, it does not exist, the trixel must be empty of sources"
                )
            data = np.array([])
        else:
            f = h5py.File(filename, "r")
            if dataset_name not in f:
                if Verbose == True:
                    print(
                        f"Cannot read Dataset <{dataset_name}> from hdf5 file <{f}>, the trixel must be empty of sources"
                    )
                f.close()
                data = np.array([])
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
                    # MemSpaceId=h5py.h5s.create_simple(TUPLE dims_tpl, TUPLE max_dims_tpl)
        return data

    def load_colnames(
        self,
        Filename,
    ):
        # NOTE: unfinished stub in upstream catsHTM. Previously opened the file
        # with h5py and leaked the handle without reading anything from it.
        # Now raises explicitly instead of silently returning None.
        raise NotImplementedError("HDF5.load_colnames is not implemented")
