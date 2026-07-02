FROM gcr.io/oss-fuzz-base/base-builder-python@sha256:53d5573ec78599bdb03dba1fea0b4d12855d126ffd0d02d1bc915da170675cf1

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY . $SRC/aion-agent
WORKDIR $SRC/aion-agent
COPY .clusterfuzzlite/build.sh $SRC/build.sh
