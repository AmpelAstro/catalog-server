import logging

from fastapi import FastAPI

from .catalogs import router as catalogs_router
from .cone_search import router as cone_search_router
from .settings import settings

logging.basicConfig(level=settings.log_level)

tags_metadata = [
    {
        "name": "catalogs",
        "description": "Listing of available catalogs",
    },
    {
        "name": "cone_search",
        "description": "Search for objects in a cone around a celestial direction",
    },
]

app = FastAPI(
    title="Ampel Catalog Matching Service",
    description="Match celestial coordinates against catsHTM and extcats catalogs",
    version="1.0.2",
    openapi_tags=tags_metadata,
    root_path=settings.root_path,
)

app.include_router(cone_search_router, prefix="/cone_search", tags=["cone_search"])
app.include_router(catalogs_router, prefix="/catalogs", tags=["catalogs"])

# If we are mounted under a (non-stripped) prefix path, create a potemkin root
# router and mount the actual root as a sub-application. This has no effect
# other than to prefix the paths of all routes with the root path.
if settings.root_path:
    wrapper = FastAPI()
    wrapper.mount(settings.root_path, app)
    app = wrapper
