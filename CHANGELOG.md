# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Fixed
- Pass pre_filter and post_filter args to CatalogQuery

## [1.0.1] - 2020-03-09
### Fixed
- Use extcats 2.4.1 for faster startup
- Cache catalog descriptions and CatalogQuery instances unconditionally
- Check that requested catsHTM catalogs actually exist on disk

## [1.0.0] - 2020-03-03
Initial release.
