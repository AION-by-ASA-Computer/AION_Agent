FROM gcr.io/oss-fuzz-base/base-builder-python

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY . $SRC/aion-agent
WORKDIR $SRC/aion-agent
COPY .clusterfuzzlite/build.sh $SRC/build.sh
