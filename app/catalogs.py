import io
import logging
import re
from functools import lru_cache
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pymongo.errors import OperationFailure

from .models import CatalogDescription
from .mongo import get_catq, get_mongo
from .settings import settings

log = logging.getLogger(__name__)


def catshtm_catalog_descriptions():
    """
    Parse metadata from catsHTM README and MATLAB files
    """
    from catsHTM import params
    from catsHTM.script import get_CatDir
    from scipy.io import loadmat

    catalogs = []
    if settings.catshtm_dir is None:
        return catalogs

    for line in io.StringIO(
        """
        2MASS (input name: TMASS)
        2MASSxsc (input name: TMASSxsc) - 2MASS extended source catalog
        AKARI (input name: AKARI)
        APASS (input name: APASS) - AAVSO All Sky Photometric Sky Survey (~5.5x10^7 sources)
        Cosmos (input name: Cosmos) - Sources in the Cosmos field
        DECaLS (input name: DECaLS) - DECaLS DR5 release
        FIRST (input name: FIRST) - (~9.5x10^5 sources)
        GAIA/DR1 (input name: GAIADR1) - (~1.1x10^9 sources).
        GAIA/DR2 (input name: GAIADR2) - NEW! (~1.6x10^9 sources)
        GALEX (input name: GALEX) - GALAEX/GR6Plus7 (~1.7x10^8 sources).
        HSC/v2 (input name: HSCv2)- Hubble source catalog
        IPHAS/DR2 (input name: IPHAS)
        NED redshifts (input name: NEDz)
        NVSS (input name: NVSS) - (~1.8x10^6 sources)
        PS1 (input name: PS1) - Pan-STARRS (~2.6x10^9 sources; A cleaned version of the PS1 stack catalog; some missing tiles below declination of zero [being corrected])
        PTFpc (input name: PTFpc) - PTF photometric catalog
        ROSATfsc (input name: ROSATfsc) - ROSAT faint source catalog
        SDSS/DR10 (input name: SDSSDR10)- Primary sources from SDSS/DR10 (last photometric release)
        Skymapper - will be added soon.
        SpecSDSS/DR14 (input name: SpecSDSS) - SDSS spectroscopic catalog
        Spitzer/SAGE (input name SAGE)
        Spitzer/IRAC (input name IRACgc) - Spitzer IRAC galactic center survey
        UCAC4 (input name: UCAC4) - (~1.1x10^8 sources)
        UKIDSS/DR10 (input name: UKIDSS)
        USNOB1 (not yet available)
        VISTA/Viking/DR3 (not yet available)
        VST/ATLAS/DR3 (input name: VSTatlas)
        VST/KiDS/DR3 (input name: VSTkids)
        WISE (input name: WISE) - ~5.6x10^8 sources
        XMM (input name: XMM)- 7.3x10^5 sources 3XMM-DR7 (Rosen et al. 2016; A&A 26, 590)
        """.strip()
    ).readlines():
        match = re.match(
            r"(?P<name>[\w/]+) \(input name: (?P<key>\w+)\)(\s*-\s*(?P<description>.*))?",
            line.strip(),
        )
        if match:
            name = match.group("key")
            try:
                meta = loadmat(
                    str(
                        settings.catshtm_dir
                        / get_CatDir(name)
                        / (params.ColCelFile % name)
                    )
                )
            except FileNotFoundError:
                continue
            catalogs.append(
                {
                    "name": name,
                    "use": "catsHTM",
                    "description": " -- ".join(
                        [
                            s
                            for s in (match.group("name"), match.group("description"))
                            if s
                        ]
                    ),
                    "reference": "https://doi.org/10.1088/1538-3873/aac410",
                    "contact": "Eran Ofek <eran.ofek@weizmann.ac.il>",
                    "columns": [
                        {"name": str(k[0]), "unit": str(u[0]) if len(u) else None}
                        for k, u in zip(
                            meta["ColCell"].flatten(), meta["ColUnits"].flatten()
                        )
                    ],
                }
            )
    return catalogs


def extcats_catalog_descriptions() -> List[Dict[str,Any]]:
    catalogs = []
    mongo = get_mongo()
    for db in mongo.list_database_names():
        if db in {"local", "config", "admin"}:
            continue
        # only return catalogs for which a CatalogQuery can be instantiated
        if (catq := get_catq(db)) is None:
            continue
        try:
            meta: Dict[str, Any] = next(
                mongo[db].get_collection("meta").find({"_id": "science"}, {"_id": 0}),
                {},
            )
        except OperationFailure:
            # unauthorized
            meta = {}
        # use first entry as an example, minus index fields
        projection = {"_id": 0, **{k: 0 for k in [catq.hp_key, catq.s2d_key] if k is not None}}
        src: Dict[str, Any] = next(catq.src_coll.find({}, projection), {})
        catalogs.append(
            {
                "name": db,
                "use": "extcats",
                "columns": [{"name": k, "unit": None} for k in src.keys()],
                "description": meta.get("description"),
                "reference": meta.get("ref"),
                "contact": f"{meta['contact']} <{meta.get('email')}>" if 'contact' in meta else None
            }
        )
    return catalogs


@lru_cache(maxsize=1)
def catalog_descriptions():
    return extcats_catalog_descriptions() + catshtm_catalog_descriptions() 


router = APIRouter()


@router.get("/", response_model=List[CatalogDescription])
def list_catalogs() -> List[CatalogDescription]:
    """
    Get set of usable catalogs
    """
    return catalog_descriptions()


@router.get("/{catalog}/{name}")
def lookup(catalog: str, name: str, mongo = Depends(get_mongo)):
    collection = mongo.get_database(catalog).get_collection("srcs")
    # ensure search will be indexed
    try:
        if not any("name" in dict(idx["key"]) for idx in collection.index_information().values()):
            raise HTTPException(status_code=404)
    except OperationFailure:
        raise HTTPException(status_code=404)
    return collection.find_one({"name": name}, {"_id": 0, "pos": 0})
