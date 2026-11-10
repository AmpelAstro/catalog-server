from typing import Annotated, Optional, Union, TYPE_CHECKING

from pydantic import (
    UrlConstraints,
    AnyHttpUrl,
    AnyUrl,
    DirectoryPath,
    Field,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    MongoUrl = str
    HttpUrl = str
else:
    MongoUrl = Annotated[
        AnyUrl, UrlConstraints(allowed_schemes=["mongodb"], host_required=False)
    ]
    HttpUrl = AnyHttpUrl


def _validate_catshtm_dir(
    v: Optional[Union[str, DirectoryPath]],
) -> Optional[Union[str, DirectoryPath]]:
    """
    Validate CATSHTM_DIR which can be either:
    - A local directory path (validated as DirectoryPath)
    - An S3 URI (starts with s3://)
    - None (disabled)
    """
    if v is None:
        return None

    # If it's an S3 URI, accept it as-is
    if isinstance(v, str) and v.startswith("s3://"):
        return v

    # Otherwise, treat it as a local directory path
    # This will be validated by DirectoryPath
    return v


class Settings(BaseSettings):
    env: str = Field("prod", validation_alias="ENV")
    app_url: AnyHttpUrl = Field(
        AnyHttpUrl("http://127.0.0.1:8080"), validation_alias="APP_URL"
    )
    root_path: str = Field("", validation_alias="ROOT_PATH")
    mongo_uri: MongoUrl = Field(
        MongoUrl("mongodb://localhost:27017"), validation_alias="MONGO_URI"
    )
    catshtm_dir: Optional[str] = Field(None, validation_alias="CATSHTM_DIR")
    log_level: str = Field("WARN", validation_alias="LOG_LEVEL")

    # Custom validator for catshtm_dir
    _validate_catshtm_dir = field_validator("catshtm_dir")(_validate_catshtm_dir)

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="allow",
    )


settings = Settings()
