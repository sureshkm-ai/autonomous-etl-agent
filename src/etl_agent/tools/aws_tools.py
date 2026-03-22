"""AWS S3 tool — handles .whl packaging and S3 upload/download."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

import boto3  # type: ignore[import]

from etl_agent.core.exceptions import ArtifactPackagingError, S3UploadError
from etl_agent.core.logging import get_logger

logger = get_logger(__name__)


class AWSTools:
    """AWS operations: S3 upload/download and .whl artifact packaging."""

    def __init__(
        self,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        region: str = "us-east-1",
        bucket: Optional[str] = None,
        endpoint_url: Optional[str] = None,
    ) -> None:
        self._bucket = bucket  # default bucket for upload_to_s3 when not specified
        self._s3 = boto3.client(
            "s3",
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=region,
            endpoint_url=endpoint_url,  # None = real AWS; set for LocalStack
        )

    def package_whl(self, pipeline_name: str, pipeline_code: str) -> str:
        """
        Package the pipeline code as a Python .whl file.

        Returns the local path to the created .whl file.
        """
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                pkg_dir = Path(tmpdir) / pipeline_name
                pkg_dir.mkdir()
                (pkg_dir / "__init__.py").touch()
                (pkg_dir / "__main__.py").write_text(pipeline_code)

                setup_py = Path(tmpdir) / "setup.py"
                setup_py.write_text(
                    f'from setuptools import setup, find_packages\n'
                    f'setup(name="{pipeline_name}", version="1.0.0", packages=find_packages())\n'
                )

                result = subprocess.run(
                    [sys.executable, "setup.py", "bdist_wheel", "--dist-dir", "/tmp/etl_artifacts"],
                    capture_output=True, text=True, cwd=tmpdir,
                )
                if result.returncode != 0:
                    raise ArtifactPackagingError(f"bdist_wheel failed: {result.stderr}")

                whl_files = list(Path("/tmp/etl_artifacts").glob(f"{pipeline_name}*.whl"))
                if not whl_files:
                    raise ArtifactPackagingError("No .whl file was produced")

                whl_path = str(whl_files[0])
                logger.info("whl_packaged", path=whl_path)
                return whl_path

        except Exception as e:
            raise ArtifactPackagingError(f"Packaging failed: {e}") from e

    def upload_to_s3(
        self,
        local_path: str,
        bucket: Optional[str] = None,
        key: Optional[str] = None,
        s3_key: Optional[str] = None,
    ) -> str:
        """Upload a file to S3 and return its S3 URL.

        ``s3_key`` is an alias for ``key`` for backwards compatibility with
        test callers that use the ``s3_key`` keyword argument.
        """
        resolved_bucket = bucket or self._bucket
        resolved_key = key or s3_key
        if not resolved_bucket:
            raise S3UploadError("bucket is required (pass 'bucket=' or set it in __init__)")
        if not resolved_key:
            raise S3UploadError("key or s3_key is required")
        try:
            self._s3.upload_file(local_path, resolved_bucket, resolved_key)
            s3_url = f"s3://{resolved_bucket}/{resolved_key}"
            logger.info("s3_upload_complete", url=s3_url)
            return s3_url
        except Exception as e:
            raise S3UploadError(f"S3 upload failed: {e}") from e

    def download_from_s3(self, bucket: str, key: str, local_path: str) -> None:
        """Download a file from S3."""
        self._s3.download_file(bucket, key, local_path)
        logger.info("s3_download_complete", bucket=bucket, key=key, local=local_path)
