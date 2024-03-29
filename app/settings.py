from typing import Optional, TYPE_CHECKING

from pydantic import (
    AnyHttpUrl,
    AnyUrl,
    BaseSettings,
    DirectoryPath,
    Field,
    stricturl,
    parse_obj_as,
)

# see: https://github.com/samuelcolvin/pydantic/issues/975#issuecomment-551147305
if TYPE_CHECKING:
    MongoUrl = AnyUrl
else:
    MongoUrl = stricturl(allowed_schemes={"mongodb"}, tld_required=False)


class Settings(BaseSettings):
    env: str = Field("prod", env="ENV")
    app_url: AnyHttpUrl = Field(parse_obj_as(AnyHttpUrl, "http://127.0.0.1:8080"), env="APP_URL")
    root_path: str = Field("", env="ROOT_PATH")
    mongo_uri: Optional[MongoUrl] = Field(parse_obj_as(MongoUrl, "mongodb://localhost:27018"), env="MONGO_URI")
    catshtm_dir: Optional[DirectoryPath] = Field(None, env="CATSHTM_DIR")

    class Config:
        env_file = ".env"


settings = Settings()
