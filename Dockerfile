# Pixi-based Dockerfile following official deployment guidelines
# Reference: https://pixi.prefix.dev/latest/deployment/container/#example-usage

FROM ghcr.io/prefix-dev/pixi:0.84.1 AS build

# copy source code, pixi.toml and pixi.lock to the container
WORKDIR /app
COPY . .
# install dependencies to `/app/.pixi/envs/default`
# use `--locked` to ensure the lock file is up to date with pixi.toml
RUN pixi install --locked
# create the shell-hook bash script to activate the environment
RUN pixi shell-hook -s bash > /shell-hook
RUN echo "#!/bin/bash" > /app/entrypoint.sh
RUN cat /shell-hook >> /app/entrypoint.sh
# extend the shell-hook script to run the command passed to the container
RUN echo 'exec "$@"' >> /app/entrypoint.sh

FROM ubuntu:24.04 AS production
WORKDIR /app
# only copy the production environment into prod container
# please note that the "prefix" (path) needs to stay the same as in the build container
COPY --from=build /app/.pixi/envs/default /app/.pixi/envs/default
COPY --from=build --chmod=0755 /app/entrypoint.sh /app/entrypoint.sh
# copy your project code into the container as well
COPY ./app /app/app

# Set PYTHONPATH so imports work correctly
ENV PYTHONPATH=/app
# Create cache dirs for astropy and friends
RUN mkdir -p --mode a=rwx /var/cache/astropy
ENV XDG_CACHE_HOME=/var/cache XDG_CONFIG_HOME=/var/cache
# use certifi CAs
ENV AWS_CA_BUNDLE=/app/.pixi/envs/default/ssl/cacert.pem

EXPOSE 80
ENTRYPOINT [ "/app/entrypoint.sh" ]
# run your app inside the pixi environment
CMD [ "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80" ]
