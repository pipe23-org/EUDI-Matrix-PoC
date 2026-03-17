# Element Web with phone number lookup patch
# Based on upstream element-web v1.12.10 Dockerfile
# Adds msisdn (phone number) IS lookup to InviteDialog

FROM node:24-bullseye AS builder

WORKDIR /src

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN corepack enable

RUN git clone --depth 1 --branch v1.12.10 \
    https://github.com/element-hq/element-web.git .

COPY invite-phone-lookup.patch .
RUN git apply invite-phone-lookup.patch

ARG USE_CUSTOM_SDKS=false
RUN /src/scripts/docker-link-repos.sh
RUN yarn --network-timeout=200000 install
RUN /src/scripts/docker-package.sh

RUN cp /src/config.sample.json /src/webapp/config.json

# --- Runtime stage ---
FROM nginxinc/nginx-unprivileged:alpine-slim

USER root
RUN apk add jq moreutils

COPY --from=builder /src/webapp /app
COPY --from=builder /src/docker/nginx-templates/ /etc/nginx/templates/
COPY --from=builder /src/docker/docker-entrypoint.d/ /docker-entrypoint.d/

RUN rm -rf /usr/share/nginx/html \
  && ln -s /app /usr/share/nginx/html

USER nginx

ENV ELEMENT_WEB_PORT=80

HEALTHCHECK --start-period=5s CMD wget -q --spider http://localhost:$ELEMENT_WEB_PORT/config.json
