# syntax=docker/dockerfile:1
#
# SYNOX 的執行用映像檔（說明、限制、驗證清單：docs/docker.md）。
#
#   docker compose build            建映像檔（用 docker-compose.yml，埠只發佈到 127.0.0.1）
#   docker compose run --rm synox init     第一次：文字版設定引導，寫進資料 volume 的 config.json
#   docker compose up -d            開
#
# 兩段式：build 段把相依套件和 SYNOX 本身打成 wheel；runtime 段只裝 wheel，不留編譯工具、不留原始碼樹。
# 只複製需要的檔案（另外 .dockerignore 是白名單，data/、config.json、.env、金鑰一律進不了 build context）。
#
# 鎖版本：預設用官方 python:3.11-slim-bookworm 的 tag。要可重現就把 PYTHON_IMAGE 換成帶 @sha256: 的寫法
# （docs/docker.md「檢查表」B1）。

ARG PYTHON_IMAGE=python:3.11-slim-bookworm

# ── build：wheel ─────────────────────────────────────────────────────────
FROM ${PYTHON_IMAGE} AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# 先只放 requirements.txt：相依沒變就重用這一層的快取（改程式不會重抓套件）
COPY requirements.txt ./
RUN python -m pip wheel --wheel-dir /wheels -r requirements.txt

# 再放 SYNOX 本身（src/synox＋原樣複製的 SDK vendor/isdtelekit；pyproject.toml 兩個都打包）
COPY pyproject.toml ./
COPY vendor/ vendor/
COPY src/ src/
RUN python -m pip wheel --no-deps --wheel-dir /wheels .

# ── runtime ──────────────────────────────────────────────────────────────
FROM ${PYTHON_IMAGE} AS runtime

ARG SYNOX_UID=10001
ARG SYNOX_GID=10001

LABEL org.opencontainers.image.title="SYNOX" \
      org.opencontainers.image.description="Self-hosted personal assistant and tool console (Telegram / Discord / local web UI)" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later AND Apache-2.0"

# SYNOX_HOME：config.json、data/、packs/、tools/ 都在這裡（config.default_root 的第一順位）；compose 掛具名 volume。
# SYNOX_IN_CONTAINER=1：只是「這是 SYNOX 的容器」的標記。網頁要不要改綁 0.0.0.0 另外看 SYNOX_WEB_BIND
# （映像檔不設；docker-compose.yml 設，並且只發佈到宿主的 127.0.0.1）。HOME 指到 tmpfs，根目錄可以唯讀。
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    SYNOX_HOME=/synox \
    SYNOX_IN_CONTAINER=1 \
    SYNOX_NO_BANNER=1 \
    SYNOX_NO_BROWSER=1 \
    HOME=/tmp \
    TZ=UTC

# tzdata：提醒、排程照「容器的時區」算（compose 的 TZ）。只裝這一個，不留 apt 的清單
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

# 非 root 帳號；/synox 先建好並交給它（第一次掛上空的具名 volume 時，Docker 會沿用這個擁有者）。
# /etc/synox/container：容器證據之一（web/server.py 的 CONTAINER_MARKERS），root 擁有、唯讀。
RUN groupadd --system --gid "${SYNOX_GID}" synox \
 && useradd --system --uid "${SYNOX_UID}" --gid synox --no-create-home --home-dir /nonexistent \
            --shell /usr/sbin/nologin synox \
 && mkdir -p /synox /etc/synox \
 && chown synox:synox /synox \
 && chmod 0750 /synox \
 && touch /etc/synox/container

# 只從 build 段的 wheel 裝（--no-index：這一步不連網）；wheel 用 bind mount 帶進來，不留在映像檔的層裡
RUN --mount=type=bind,from=build,source=/wheels,target=/wheels \
    python -m pip install --no-index --find-links=/wheels synox

COPY LICENSE LICENSE-APACHE NOTICE LICENSING.md /usr/share/doc/synox/
COPY docker/healthcheck.py /opt/synox/healthcheck.py

USER synox:synox
WORKDIR /synox
VOLUME ["/synox"]

# 只是文件：容器裡網頁的埠（config.json 的 web.port，預設 8830）。真的發佈與否、發佈到哪裡由 compose 決定
EXPOSE 8830

# 健康檢查不經任何對外的埠：看 data/host.lock 的那支程式還活著，網頁開著的話連容器自己的 127.0.0.1
HEALTHCHECK --interval=60s --timeout=10s --start-period=60s --retries=3 \
    CMD ["python", "/opt/synox/healthcheck.py"]

ENTRYPOINT ["synox"]
CMD ["run", "--no-browser"]
