#!/usr/bin/env bash
# =============================================================================
# build_layer.sh — Build the pyarrow Lambda layer ZIP
#
# Run from the repo root:
#   bash infra/lambda/schema_detector/build_layer.sh
#
# Output: infra/lambda/pyarrow-layer.zip
#
# The Lambda layer ZIP structure must match the format expected by AWS:
#   python/
#   python/pyarrow/
#   python/pyarrow/...
#
# The zip is committed to the repo (or uploaded to S3) and referenced by
# the aws_lambda_layer_version resource in infra/terraform/iceberg.tf.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
BUILD_DIR="${SCRIPT_DIR}/.layer_build"
OUTPUT_ZIP="${REPO_ROOT}/infra/lambda/pyarrow-layer.zip"

echo "Building pyarrow Lambda layer..."
echo "  Script dir : ${SCRIPT_DIR}"
echo "  Build dir  : ${BUILD_DIR}"
echo "  Output ZIP : ${OUTPUT_ZIP}"

# Clean previous build
rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}/python"

# Install pyarrow into the layer directory
# Using --platform to ensure Linux-compatible binaries (manylinux2014_x86_64)
pip install \
    --platform manylinux2014_x86_64 \
    --target "${BUILD_DIR}/python" \
    --implementation cp \
    --python-version 3.12 \
    --only-binary=:all: \
    --upgrade \
    pyarrow==15.0.2

echo "Installed packages:"
ls -lh "${BUILD_DIR}/python/"

# Package into ZIP
cd "${BUILD_DIR}"
zip -r "${OUTPUT_ZIP}" python/ -q

echo ""
echo "Layer ZIP created: ${OUTPUT_ZIP}"
echo "Size: $(du -sh "${OUTPUT_ZIP}" | cut -f1)"
echo ""
echo "Next step: run 'terraform apply' to deploy the updated layer."

# Clean up build directory
rm -rf "${BUILD_DIR}"
