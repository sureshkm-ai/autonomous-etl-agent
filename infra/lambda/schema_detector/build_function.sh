#!/usr/bin/env bash
# =============================================================================
# build_function.sh — Build the schema_detector Lambda function ZIP
#
# Run from the repo root:
#   bash infra/lambda/schema_detector/build_function.sh
#
# Output: infra/lambda/schema_detector.zip
#
# Packages handler.py + schema_reader.py + glue_helper.py only.
# pyarrow is provided by the Lambda layer (pyarrow-layer.zip), NOT bundled here.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
OUTPUT_ZIP="${REPO_ROOT}/infra/lambda/schema_detector.zip"

echo "Building schema_detector Lambda function ZIP..."

# Package the three Python modules only
cd "${SCRIPT_DIR}"
zip -j "${OUTPUT_ZIP}" \
    handler.py \
    schema_reader.py \
    glue_helper.py

echo ""
echo "Function ZIP created: ${OUTPUT_ZIP}"
echo "Size: $(du -sh "${OUTPUT_ZIP}" | cut -f1)"
echo "Contents:"
unzip -l "${OUTPUT_ZIP}"
echo ""
echo "Next step: run 'terraform apply' to deploy the updated function."
