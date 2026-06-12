# DualCore web app image.
#
# This container talks to the host Docker daemon (via a mounted socket — see
# docker-compose.yml) to launch sandbox containers as siblings, so it ships with
# only the Docker *CLI*, not a full engine.
FROM python:3.12-slim

# Docker CLI (static binary, amd64). For arm64 hosts, swap x86_64 -> aarch64.
ARG DOCKER_CLI_VERSION=27.3.1
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && curl -fsSL "https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKER_CLI_VERSION}.tgz" \
      | tar -xz -C /usr/local/bin --strip-components=1 docker/docker \
 && apt-get purge -y curl && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV SANDBOX=docker \
    FLASK_DEBUG=0 \
    PORT=8000
EXPOSE 8000

CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000", \
     "--timeout", "300", "--workers", "2", "--threads", "4"]
