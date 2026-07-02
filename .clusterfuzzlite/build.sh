#!/bin/bash -eu
# ClusterFuzzLite build script for Python fuzz targets (Atheris).
# PyInstaller onefile bundles traced imports at build time; fuzzers must use
# normal package imports (not filesystem paths via __file__).

cd "$SRC/aion-agent"
export PYTHONPATH="$SRC/aion-agent${PYTHONPATH:+:$PYTHONPATH}"

pip3 install --no-cache-dir --require-hashes -r requirements-fuzz.txt

for fuzzer in $(find "$SRC/aion-agent/fuzz" -name '*_fuzzer.py'); do
  compile_python_fuzzer "$fuzzer"
done
