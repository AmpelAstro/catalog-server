"""*******************************************************
A python implementation of catsHTM.m
******************************************************"""
# print __doc__

import math
from functools import lru_cache

import numpy as np

from . import celestial, io, params

__all__ = [
    "cone_search",
    "htm_search_cone",
    "search_htm_ind",
]  # redefinition of '*' for import *


def cone_search(
    CatName,
    RA,
    Dec,
    Radius,
    catalogs_dir="./data",
    RadiusUnits="arcsec",
    IndexFileTemplate=params.IndexFileTemplate,
    CatFileTemplate=params.CatFileTemplate,
    htmTemplate=params.htmTemplate,
    NcatinFile=params.NcatinFile,
    IndexVarname=None,
    ColRa=0,
    ColDec=1,
    OnlyCone=True,
    ColCelFile=params.ColCelFile,
    OutType="np_array",
    verbose=False,
):
    """Description: Perform a cone search around RA/Dec on a local catalog in HDF5 format sorted into HTM.
    Input  : - Catalog name (e.g., 'GAIADR1').
            - J2000.0 R.A. [radians, [H M S], or sexagesimal string].
            - J2000.0 Dec. [radians, [sign D M S], or sexagesimal string].
            - Search radius [arcsec].
            - Optionnal:RadiusUnits - Radius units. Default is 'arcsec'. DO NOT CHANGE THIS DEFAULT
                        IndexFileTemplate - Index Catalog name template. Default is '%s_htm.hdf5'.
                        CatFileTemplate - Catalog name template. Default is '%s_htm_%06d.hdf5'.
                        htmTemplate - HTM dataset template name. Default is 'htm_%06d'.
                        NcatInFile  - Maximum number of Datasets in file.Default is 100.
                        IndexVarName - Default is None.
                        ColRA       - Default is 1.
                        ColDec      - Default is2.
                        OnlyCone    - Return only sources within cone. If false will return also some objects outside cone. Default is true.
                        ColCellFile - Default is '%s_htmColCell.mat'.
    By : Maayane Soumagnac (original Matlab function by Eran Ofek)            Feb 2018
    Output  : a numpy array where each line is the catalog line for the sources inside the cone"""
    # start_time=time.time()
    if verbose == True:
        print("*************")
        print(
            f"Catalog: {CatName}; cone radius: {Radius} arcsec; cone center: (RA,DEC)=({RA},{Dec})"
        )
        print("*************")

    root_to_data = catalogs_dir + "/"
    CatDir = io.get_CatDir(CatName)

    Rad = 180.0 / math.pi

    # if RadiusUnits=='arcsec':
    Radius = Radius / (Rad * 3600)  # converts arcsec radius into radians radius

    IndexFilename = IndexFileTemplate % CatName

    # Load ColCell data using io module
    _Ncol, ColCell, ColUnits = io.load_colcell(catalogs_dir, CatName)
    ### computes the list of index of the trixels which intercept the cone
    ID = search_htm_ind(
        IndexFilename,
        RA,
        Dec,
        Radius,
        catalogs_dir,
        VarName=IndexVarname,
        CatDir=CatDir,
        verbose=verbose,
    )  # list of IDs of winners leaf
    ### computes the catalog with the sources located in those trixels
    ID_matlab = ID + 1
    FileID = np.floor(ID_matlab / NcatinFile) * NcatinFile
    Nid = len(ID_matlab)  # number of leaf intercepting the circle

    if Nid == 0:  # if none of the catalog's trixel intercept the cone
        if verbose == True:
            print("INFO: the cone does not intercept the catalog")
        cat_onlycone = np.array([])
    else:
        FileName_0 = CatFileTemplate % (CatName, FileID[0])
        DataName_0 = htmTemplate % ID_matlab[0]
        cat = io.load_hdf5_dataset(
            root_to_data + CatDir + "/" + FileName_0, DataName_0
        ).T
        for Iid in range(Nid)[1:]:
            FileName = CatFileTemplate % (CatName, FileID[Iid])
            DataName = htmTemplate % ID_matlab[Iid]

            cat = np.vstack(
                (
                    cat,
                    io.load_hdf5_dataset(
                        root_to_data + CatDir + "/" + FileName, DataName
                    ).T,
                )
            )
        # if OnlyCone==True:
        D = celestial.sphere_distance_fast(
            RA, Dec, cat[:, ColRa], cat[:, ColDec]
        )  # [0]
        cat_onlycone = cat[D < Radius, :]

    ### a column with the cell names:
    # Reuse ColCell/ColUnits loaded earlier
    # If cat_onlycone has a different number of columns, trim ColCell/ColUnits to match
    if cat_onlycone.ndim > 1:
        actual_ncol = np.shape(cat_onlycone)[1]
        if actual_ncol < len(ColCell):
            ColCell = ColCell[:actual_ncol]
            ColUnits = ColUnits[:actual_ncol]

    return cat_onlycone, ColCell, ColUnits


# get_index_data is now in io module (imported above)


def search_htm_ind(
    Filename, Long, Lat, Radius, path, VarName=None, CatDir=None, verbose=False
):
    """Description: wrapper of htm_search_cone, which select from the vector outputed by htm_search_cone only the
    triangles where there are actually sources.
            Input  : - Filename: the name of the index_file, e.g. FIRST_htm.hdf5
            Output :
            By : Maayane Soumagnac (original Matlab function by Eran Ofek)            Feb 2018

    """
    if VarName == None:
        cat_name = Filename.split("_")[0]
        VarName = cat_name + "_HTM"

    DataHTM_indexfile = io.get_index_data(path, CatDir, Filename, VarName)

    ID = htm_search_cone(
        DataHTM_indexfile, Long, Lat, Radius
    )  # ,Son_index=Son_index,PolesLong_index=PolesLong_index,PolesLat_index=PolesLat_index) # returns a list of the ID of the winners mesh, i.e. the meshes that intercept the circle

    ID_array = np.array(ID)
    ID_w_sources = ID_array[DataHTM_indexfile[12, ID] > 0]  # ou l inverse?
    return ID_w_sources


# Row offsets into the HTM index file. These are read-only, so hoisting them out
# of the argument defaults avoids re-allocating the arrays on every call.
SON_INDEX = np.arange(2, 6)
POLES_LONG_INDEX = np.arange(6, 11, 2)
POLES_LAT_INDEX = np.arange(7, 12, 2)


def htm_search_cone(
    IndexFile_data,
    Long,
    Lat,
    Radius,
    Ind=None,
    Son_index=SON_INDEX,
    PolesLong_index=POLES_LONG_INDEX,
    PolesLat_index=POLES_LAT_INDEX,
):
    """Description: Search for all HTM leafs intersecting a small circles
    Input  :-Either a table of HTM data or an open HDF5 object in which the HTM data is stored
            -Longitude (radians) to search
            -Latitutde (radians) to search
            -Radius of the small circle
    Output : a vector of indexes of the winner(s):the "adress" in the indexfile of the smallest leaf(s) intercepting the cone
    By : Maayane Soumagnac (original Matlab function by Eran Ofek)            Feb 2018

    """
    if Ind is None:
        Sons = np.arange(8)
    else:
        Sons = Ind.astype(int)
    ID = []
    Nsons = len(Sons)
    PolesLong = np.zeros(
        (3, Nsons)
    )  # 3 lines, Nsons colomns, on veut mettre a chaque colomne les longitudes des poles du mesh
    PolesLat = np.zeros((3, Nsons))  # 3 lignes, Nsons colomnes

    for i in range(Nsons):  # OPTIMIZE
        PolesLong[:, i] = IndexFile_data[
            PolesLong_index[:], Sons[i]
        ]  # array where each colomn is the 3 poles longitudes of a son mesh HERE: THIS? OR INVERSE?
        PolesLat[:, i] = IndexFile_data[
            PolesLat_index[:], Sons[i]
        ]  # array where each colomn is the 3 poles latitude of a son mesh HERE: THIS? OR INVERSE?

    Flag = celestial.cone_in_polysphere(
        PolesLong, PolesLat, Long, Lat, Radius
    )  # check if the cone intercept any of the sons meshes

    for i in range(Nsons):  # OPTIMIZABLE?
        if Flag[i] == 1:  # i.e. if the cone overlap the son with index i
            if (
                np.isnan(IndexFile_data[Son_index[:], Sons[i]]).all() == True
            ):  # there are nans in the index_file at the son's index, which means the data is where you are and you cannot go further in the tree
                ID.append(Sons[i])
            else:
                Ind = IndexFile_data[Son_index[:], Sons[i]] - 1.0
                # RECURION IS HERE
                ID.extend(htm_search_cone(IndexFile_data, Long, Lat, Radius, Ind=Ind))

    return ID

    # return simplify2(IDc)
