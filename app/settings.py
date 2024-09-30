from typing import Annotated, Optional, TYPE_CHECKING

from pydantic import (
    UrlConstraints,
    AnyHttpUrl,
    AnyUrl,
    DirectoryPath,
    Field,
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


class Settings(BaseSettings):
    env: str = Field("prod", validation_alias="ENV")
    app_url: AnyHttpUrl = Field(AnyHttpUrl("http://127.0.0.1:8080"), validation_alias="APP_URL")
    root_path: str = Field("", validation_alias="ROOT_PATH")
    mongo_uri: MongoUrl = Field(MongoUrl("mongodb://localhost:27018"), validation_alias="MONGO_URI")
    catshtm_dir: Optional[DirectoryPath] = Field(None, validation_alias="CATSHTM_DIR")
    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
