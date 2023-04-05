import sys
from typing import Any, Dict, List, Optional, Sequence, Union

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal

from catsHTM.script import get_CatDir, params
from pydantic import BaseModel, Field, validator

from .mongo import get_catq
from .settings import settings


class CatalogQueryItem(BaseModel):
    name: str = Field(..., description="Name of catalog")
    rs_arcsec: float = Field(..., description="Search radius in arcseconds")
    keys_to_append: Optional[Sequence[str]] = Field(
        None,
        description="Fields from catalog record to include in result. If null, return the entire record.",
    )


class ExtcatsQueryItem(CatalogQueryItem):
    use: Literal["extcats"] = "extcats"
    pre_filter: Optional[Dict[str, Any]] = Field(
        None, description="Filter condition to apply before index search"
    )
    post_filter: Optional[Dict[str, Any]] = Field(
        None, description="Filter condition to apply after index search"
    )

    @validator("name")
    def check_name(cls, value):
        if (catq := get_catq(value)) is None:
            raise ValueError(f"Unknown extcats catalog '{value}'")
        return value


class CatsHTMQueryItem(CatalogQueryItem):
    use: Literal["catsHTM"] = "catsHTM"

    @validator("name")
    def check_name(cls, value):

        try:
            if not (
                settings.catshtm_dir / get_CatDir(value) / (params.ColCelFile % value)
            ).exists():
                raise FileNotFoundError
        except:
            raise ValueError(f"Unknown catsHTM catalog '{value}'")
        return value


class CatalogItem(BaseModel):
    body: Dict[str, Any]
    dist_arcsec: float


class ConeSearchRequest(BaseModel):
    ra_deg: float = Field(
        ..., description="Right ascension (J2000) of field center in degrees"
    )
    dec_deg: float = Field(
        ..., description="Declination (J2000) of field center in degrees", ge=-90, le=90
    )
    catalogs: Sequence[Union[ExtcatsQueryItem, CatsHTMQueryItem]]


class CatalogField(BaseModel):
    name: str
    unit: Optional[str]


class CatalogDescription(BaseModel):
    name: str
    use: Literal["extcats", "catsHTM"]
    description: Optional[str]
    reference: Optional[str]
    contact: Optional[str]
    columns: List[CatalogField]
