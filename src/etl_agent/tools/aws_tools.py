"""AWS S3 tool — handles .whl packaging and S3 upload/download."""
import os
import subprocess
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
        aws_access_key_id: str,
        aws_secret_access_key: str,
        region: str,
        endpoint_url: Optional[str] = None,
    ) -> None:
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
                    ["python", "setup.py", "bdist_wheel", "--dist-dir", "/tmp/etl_artifacts"],
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

    def upload_to_s3(self, local_path: str, bucket: str, key: str) -> str:
        """Upload a file to S3 and return its S3 URL."""
        try:
            self._s3.upload_file(local_path, bucket, key)
            s3_url = f"s3://{bucket}/{key}"
            logger.info("s3_upload_complete", url=s3_url)
            return s3_url
        except Exception as e:
            raise S3UploadError(f"S3 upload failed: {e}") from e

    def download_from_s3(self, bucket: str, key: str, local_path: str) -> None:
        """Download a file from S3."""
        self._s3.download_file(bucket, key, local_path)
        logger.info("s3_download_complete", bucket=bucket, key=key, local=local_path)
