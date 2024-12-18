import sys
from typing import Any, Dict, List, Optional, Sequence, Union
from pydantic import field_validator

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal

if sys.version_info >= (3, 9):
    from typing import Annotated
else:
    from typing_extensions import Annotated

from catsHTM.script import get_CatDir, params
from pydantic import BaseModel, Field

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

    @field_validator("name")
    @classmethod
    def check_name(cls, value):
        if get_catq(value) is None:
            raise ValueError(f"Unknown extcats catalog '{value}'")
        return value


class CatsHTMQueryItem(CatalogQueryItem):
    use: Literal["catsHTM"] = "catsHTM"

    @field_validator("name")
    @classmethod
    def check_name(cls, value):

        try:
            if not (
                settings.catshtm_dir / get_CatDir(value) / (params.ColCelFile % value)
            ).exists():
                raise FileNotFoundError
        except (ValueError, FileNotFoundError) as exc:
            raise ValueError(f"Unknown catsHTM catalog '{value}'") from exc
        return value

QueryItem = Annotated[Union[ExtcatsQueryItem, CatsHTMQueryItem], Field(discriminator="use")]

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
    catalogs: Sequence[QueryItem]


class CatalogField(BaseModel):
    name: str
    unit: Optional[str] = None


class CatalogDescription(BaseModel):
    name: str
    use: Literal["extcats", "catsHTM"]
    description: Optional[str] = None
    reference: Optional[str] = None
    contact: Optional[str] = None
    columns: List[CatalogField]
