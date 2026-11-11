from collections.abc import Sequence
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator

from .catsHTM.script import get_CatDir, params
from .mongo import get_catq
from .settings import settings


class CatalogQueryItem(BaseModel):
    name: str = Field(..., description="Name of catalog")
    rs_arcsec: float = Field(..., description="Search radius in arcseconds")
    keys_to_append: Sequence[str] | None = Field(
        None,
        description="Fields from catalog record to include in result. If null, return the entire record.",
    )


class ExtcatsQueryItem(CatalogQueryItem):
    use: Literal["extcats"] = "extcats"
    pre_filter: dict[str, Any] | None = Field(
        None, description="Filter condition to apply before index search"
    )
    post_filter: dict[str, Any] | None = Field(
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
        # If CATSHTM_DIR is not set, skip validation
        if settings.catshtm_dir is None:
            return value

        # For S3 URIs, we can't easily check file existence without making a network call
        # So we skip the existence check for S3 URIs
        # For local paths, perform the existence check
        if isinstance(settings.catshtm_dir, str) and settings.catshtm_dir.startswith(
            "s3://"
        ):
            # S3 URI - skip existence check (will be validated when actually used)
            return value

        # Local path - perform existence check
        try:
            from pathlib import Path

            file_path = (
                Path(settings.catshtm_dir)
                / get_CatDir(value)
                / (params.ColCelFile % value)
            )
            if not file_path.exists():
                raise FileNotFoundError
        except (ValueError, FileNotFoundError) as exc:
            raise ValueError(f"Unknown catsHTM catalog '{value}'") from exc
        return value


QueryItem = Annotated[ExtcatsQueryItem | CatsHTMQueryItem, Field(discriminator="use")]


class CatalogItem(BaseModel):
    body: dict[str, Any]
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
    unit: str | None = None


class CatalogDescription(BaseModel):
    name: str
    use: Literal["extcats", "catsHTM"]
    description: str | None = None
    reference: str | None = None
    contact: str | None = None
    columns: list[CatalogField]
