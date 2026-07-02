#!/bin/bash -eu
# ClusterFuzzLite build script for Python fuzz targets (Atheris).

cd "$SRC/aion-agent"

pip3 install --no-cache-dir atheris croniter pyyaml bcrypt

for fuzzer in $(find "$SRC/aion-agent/fuzz" -name '*_fuzzer.py'); do
  compile_python_fuzzer "$fuzzer"
done
