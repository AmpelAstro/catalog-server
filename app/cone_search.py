import math
from functools import singledispatch
from typing import Any, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.table import Table
from catsHTM import cone_search
from extcats.catquery_utils import get_closest, get_distances
from fastapi import APIRouter

from .models import (
    CatalogItem,
    CatsHTMQueryItem,
    ConeSearchRequest,
    ExtcatsQueryItem,
)
from .mongo import CatalogQuery, get_catq
from .settings import settings

if TYPE_CHECKING:
    from astropy.table.row import Row


def sanitize_json(obj):
    if isinstance(obj, dict):
        return {k: sanitize_json(v) for k, v in obj.items()}
    elif isinstance(obj, (tuple, list)):
        return [sanitize_json(v) for v in obj]
    elif isinstance(obj, float) and math.isnan(obj):
        return None
    elif hasattr(obj, "tolist"):
        # general conversion from numpy to python types
        return obj.tolist()
    else:
        return obj


def table_to_json(
    table: "Table",
    allow_keys: Optional[Set[str]],
    disallow_keys: Set[str] = set(),
) -> List[Dict[str, Any]]:
    keys = table.keys()
    rows = [
        {
            k: sanitize_json(v)
            for k, v in zip(keys, row)
            if (allow_keys is None or k in allow_keys)
        }
        for row in table.iterrows()
    ]
    for row in rows:
        assert not any(isinstance(c, np.int64) for c in row.values())
    return [
        {
            k: sanitize_json(v)
            for k, v in zip(keys, np.asarray(row).tolist())
            if (allow_keys is None or k in allow_keys) and (k not in disallow_keys)
        }
        for row in table.iterrows()
    ]

def row_to_json(
    row: "Row",
    allow_keys: Optional[Set[str]],
    disallow_keys: Set[str] = set(),
) -> Dict[str, Any]:
    keys = row.table.keys()
    return {
        k: sanitize_json(v)
        for k, v in zip(keys, row)
        if (allow_keys is None or k in allow_keys) and (k not in disallow_keys)
    }


@singledispatch
def search_any_item(item, coord: SkyCoord) -> bool:
    raise NotImplementedError
    return False


@singledispatch
def search_nearest_item(item, coord: SkyCoord) -> Optional[CatalogItem]:
    raise NotImplementedError
    return False


@singledispatch
def search_all_item(item, coord: SkyCoord) -> Optional[List[CatalogItem]]:
    raise NotImplementedError
    return None


@search_any_item.register  # type: ignore[no-redef]
def _(item: CatsHTMQueryItem, coord: SkyCoord) -> bool:
    srcs, colnames, colunits = cone_search(
        item.name,
        coord.ra.rad,
        coord.dec.rad,
        item.rs_arcsec,
        catalogs_dir=str(settings.catshtm_dir),
    )
    return len(srcs) > 0


@search_nearest_item.register  # type: ignore[no-redef]
def _(item: CatsHTMQueryItem, coord: SkyCoord) -> Optional[CatalogItem]:  # type: ignore[no-redef]
    srcs, colnames, colunits = cone_search(
        item.name,
        coord.ra.rad,
        coord.dec.rad,
        item.rs_arcsec,
        catalogs_dir=str(settings.catshtm_dir),
    )
    if not len(srcs):
        return None
    srcs_tab = Table(np.asarray(srcs), names=colnames)
    srcs_tab["_ra"] = np.degrees(srcs_tab[colnames[0]])
    srcs_tab["_dec"] = np.degrees(srcs_tab[colnames[1]])
    row, dist = get_closest(
        coord.ra.degree,
        coord.dec.degree,
        srcs_tab,
        "_ra",
        "_dec",
    )
    output_keys = set(colnames if item.keys_to_append is None else item.keys_to_append)
    return CatalogItem(body=row_to_json(row, output_keys), dist_arcsec=dist)


@search_all_item.register  # type: ignore[no-redef]
def _(item: CatsHTMQueryItem, coord: SkyCoord) -> Optional[List[CatalogItem]]:
    srcs, colnames, colunits = cone_search(
        item.name,
        coord.ra.rad,
        coord.dec.rad,
        item.rs_arcsec,
        catalogs_dir=str(settings.catshtm_dir),
    )
    if not len(srcs):
        return None
    srcs_tab = Table(np.asarray(srcs), names=colnames)
    srcs_tab["_ra"] = np.degrees(srcs_tab[colnames[0]])
    srcs_tab["_dec"] = np.degrees(srcs_tab[colnames[1]])
    dists = get_distances(
        coord.ra.degree,
        coord.dec.degree,
        srcs_tab,
        "_ra",
        "_dec",
    )
    output_keys = set(colnames if item.keys_to_append is None else item.keys_to_append)
    rows = table_to_json(srcs_tab, output_keys)
    return [
        CatalogItem(
            body=row,
            dist_arcsec=dist,
        )
        for row, dist in zip(rows, dists)
    ]


@search_any_item.register  # type: ignore[no-redef]
def _(item: ExtcatsQueryItem, coord: SkyCoord) -> bool:
    # sic
    if (catq := get_catq(item.name)) is None:
        raise ValueError(f"{item.name} is not a valid extcats catalog")
    else:
        return catq.binaryserach(
            coord.ra.deg,
            coord.dec.deg,
            item.rs_arcsec,
            pre_filter=item.pre_filter,
            post_filter=item.post_filter,
        )


def get_catq_with_projection(
    item: ExtcatsQueryItem,
) -> Tuple[CatalogQuery, Dict[str, Any], Optional[Set[str]], Set[str]]:
    if (catq := get_catq(item.name)) is None:
        raise ValueError(f"{item.name} is not a valid extcats catalog")
    # do not return structured index fields
    remove_keys = set([k for k in [catq.hp_key, catq.s2d_key] if k is not None])
    remove_keys.update({"_ra", "_dec"})
    if item.keys_to_append is None:
        projection = {"_id": 0}
        output_keys = None
    else:
        projection = {
            "pos": 1,
            catq.ra_key: 1,
            catq.dec_key: 1,
            **{k: 1 for k in item.keys_to_append},
        }
        output_keys = set(item.keys_to_append).difference({"_id"}.union(remove_keys))
    return catq, projection, output_keys, remove_keys


@search_nearest_item.register  # type: ignore[no-redef]
def _(item: ExtcatsQueryItem, coord: SkyCoord) -> Optional[CatalogItem]:  # type: ignore[no-redef]
    catq, projection, allow_keys, disallow_keys = get_catq_with_projection(item)
    row, dist = catq.findclosest(
        coord.ra.deg,
        coord.dec.deg,
        item.rs_arcsec,
        projection=projection,
        pre_filter=item.pre_filter,
        post_filter=item.post_filter,
    )
    if row:
        return CatalogItem(
            body=row_to_json(row, allow_keys, disallow_keys),
            dist_arcsec=dist,
        )
    else:
        return None


@search_all_item.register  # type: ignore[no-redef]
def _(item: ExtcatsQueryItem, coord: SkyCoord) -> Optional[List[CatalogItem]]:
    catq, projection, allow_keys, disallow_keys = get_catq_with_projection(item)
    srcs_tab = catq.findwithin(
        coord.ra.deg,
        coord.dec.deg,
        item.rs_arcsec,
        projection=projection,
        pre_filter=item.pre_filter,
        post_filter=item.post_filter,
    )
    if srcs_tab:
        dists = get_distances(
            coord.ra.degree,
            coord.dec.degree,
            srcs_tab,
            catq.ra_key,
            catq.dec_key,
        )
        rows = table_to_json(srcs_tab, allow_keys, disallow_keys)
        return [
            CatalogItem(body=row, dist_arcsec=dist) for row, dist in zip(rows, dists)
        ]
    else:
        return None


router = APIRouter()


@router.post("/any", response_model=List[bool])
def search_any(request: ConeSearchRequest) -> List[bool]:
    """
    Are there sources in the search radius?
    """
    coord = SkyCoord(request.ra_deg, request.dec_deg, unit="deg")
    return [search_any_item(item, coord) for item in request.catalogs]


@router.post("/nearest", response_model=List[Optional[CatalogItem]])
def search_nearest(request: ConeSearchRequest) -> List[Optional[CatalogItem]]:
    """
    Find nearest source in search radius
    """
    coord = SkyCoord(request.ra_deg, request.dec_deg, unit="deg")
    return [search_nearest_item(item, coord) for item in request.catalogs]


@router.post("/all", response_model=List[Optional[List[CatalogItem]]])
def search_all(request: ConeSearchRequest) -> List[Optional[List[CatalogItem]]]:
    """
    Find all sources in the search radius
    """
    coord = SkyCoord(request.ra_deg, request.dec_deg, unit="deg")
    return [search_all_item(item, coord) for item in request.catalogs]
