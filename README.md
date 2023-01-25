# catalog-server

`catalog-server` provides cone searches against [extcats](https://github.com/MatteoGiomi/extcats) and [catsHTM](https://github.com/maayane/catsHTM) catalogs via a REST API. It is strictly read-only, and safe to expose to anonymous users with appropriate rate-limiting.

A [Unit](https://unit.nginx.org)-based container is available at [ampelproject/catalog-server](https://hub.docker.com/r/ampelproject/catalog-server).

## Usage examples

Cone search for nearest source in a single catalog
```shell
> curl -s -X POST --header "Content-Type: application/json" http://localhost:8500/cone_search/nearest --data '{"ra_deg": 0, "dec_deg": 0, "catalogs": [{"name": "PS1", "use": "catsHTM", "rs_arcsec": 600}]}' | jq
[
  {
    "body": {
      "RA": 9.596099480145143e-05,
      "Dec": -5.788890609722272e-05,
      "ErrRA": 0.001,
      "ErrDec": 0.001,
      "MeanEpoch": 55989.22180556,
      "posMeanChi2": 1.3364,
      "gPSFMag": -999,
      "gPSFMagErr": -999,
      "gpsfLikelihood": null,
      "gMeanPSFMagStd": -999,
      "gMeanPSFMagNpt": 0,
      "gMeanPSFMagMin": -999,
      "gMeanPSFMagMax": -999,
      "rPSFMag": 22.0139,
      "rPSFMagErr": 0.186498,
      "rpsfLikelihood": null,
      "rMeanPSFMagStd": -999,
      "rMeanPSFMagNpt": 1,
      "rMeanPSFMagMin": 22.0139,
      "rMeanPSFMagMax": 22.0139,
      "iPSFMag": 21.7694,
      "iPSFMagErr": 0.022677,
      "ipsfLikelihood": null,
      "iMeanPSFMagStd": 0.045144,
      "iMeanPSFMagNpt": 4,
      "iMeanPSFMagMin": 21.7291,
      "iMeanPSFMagMax": 21.8282,
      "zPSFMag": 21.201,
      "zPSFMagErr": 0.036762,
      "zpsfLikelihood": null,
      "zMeanPSFMagStd": 0.073169,
      "zMeanPSFMagNpt": 2,
      "zMeanPSFMagMin": 21.1278,
      "zMeanPSFMagMax": 21.2013,
      "yPSFMag": -999,
      "yPSFMagErr": -999,
      "ypsfLikelihood": null,
      "yMeanPSFMagStd": -999,
      "yMeanPSFMagNpt": 0,
      "yMeanPSFMagMin": -999,
      "yMeanPSFMagMax": -999
    },
    "dist_arcsec": 23.116053641503775
  }
]
```

Veto search against multiple catalogs:
```shell
> curl -s -X POST --header "Content-Type: application/json" http://localhost:8500/cone_search/any --data '{"ra_deg": 0.00549816, "dec_deg": -0.00331679, "catalogs": [{"name": "GAIADR2", "use": "catsHTM", "rs_arcsec": 3}, {"name": "varstars", "use": "extcats", "rs_arcsec": 3}]}' | jq
[
  false,
  false
]
```

## Deploy your own catalog-server

1. Download the [catsHTM catalog files](https://euler1.weizmann.ac.il/catsHTM/) (~1.9 TB).

2. Start an instance of MongoDB and [populate it with extcats catalogs](https://github.com/MatteoGiomi/extcats/blob/8b9360d77d25b5d9b3c246368731d21fb56f72fa/notebooks/insert_example.ipynb). Ensure that the `meta` collection of each extcats database contains a document of the form: `{"_id": "keys", "ra": "RAJ2000", "dec": "DECJ2000"}`, where the "ra" and "dec" keys indicate the fields in the `srcs` documents that contain the right ascension and declination of the source in degrees. This is currently necessary to calculate distances for both geoJSON and HEALpix-indexed catalogs, and may be improved in the future.

3. Start `catalog-server` in Nginx Unit with e.g. `docker run -d -v /path/to/catsHTM/catalogs:/data/catsHTM -v $(pwd)/config.json:/docker-entrypoint.d/config.json ampelproject/catalogserver:latest`, where `config.json` is

```json
{
        "certificates": {},
        "config": {
                "listeners": {
                        "*:8500": {
                                "pass": "applications/catalog-server"
                        }
                },

                "applications": {
                        "catalog-server": {
                                "type": "python 3.7",
                                "path": "/www",
                                "module": "app.main",
                                "callable": "app",
                                "environment": {
                                        "MONGO_URI": "mongodb://user:password@mongo-instance:27017",
                                        "CATSHTM_DIR": "/data/catsHTM"
                                },

                                "processes": {
                                        "max": 4,
                                        "spare": 1,
                                        "idle_timeout": 30
                                }
                        }
                }
        }
}
```

where `mongodb://user:password@mongo-instance:27017` should be replaced with a MongoDB URI that can be used to connect as the (read-only) catalog user.

Daemonless container runtimes require slightly different options, e.g. for Singularity:

```shell
singularity run --containall \
    -B $(pwd)/config.json:/docker-entrypoint.d/config.json:ro \
    -B $(pwd)/state:/var/lib/unit \
    -B $(pwd)/run:/run \
    -B $(pwd)/log:/var/log \
    -B /data/ampel/catalogs/catsHTM2:/data/catsHTM:ro \
    /data/ampel/singularity/catalog-server_latest.sif \
    unitd --no-daemon
```

where `state`, `run`, and `log` are local directories writable by the user executing `singularity`.

## Run tests locally

docker run --rm -d --name extcats -p 27021:27017 -e MONGO_INITDB_ROOT_USERNAME=root -e MONGO_INITDB_ROOT_PASSWORD=12345 -v $(pwd)/tests/test-data/minimongodumps:/docker-entrypoint-initdb.d mongo:5
MONGO_URI=mongodb://nobody:seekrit@localhost:27021 pytest