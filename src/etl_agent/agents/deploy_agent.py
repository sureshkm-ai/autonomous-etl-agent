"""
Deploy Agent — packages the pipeline as a .whl, uploads to S3, triggers Airflow.
Inherits ReactAgent:
  - Tool loop retries S3 upload on transient network errors.
  - Tool loop retries Airflow trigger on transient errors.
Non-blocking: failures are logged but the pipeline status is set to DONE
so a deploy hiccup never fails an otherwise successful run.
"""

from typing import Any

from etl_agent.agents.base import ReactAgent
from etl_agent.core.config import get_settings
from etl_agent.core.exceptions import AirflowTriggerError, S3UploadError
from etl_agent.core.logging import get_logger
from etl_agent.core.models import RunStatus
from etl_agent.core.state import GraphState
from etl_agent.tools.aws_tools import AWSTools

logger = get_logger(__name__)


class DeployAgent(ReactAgent):
    """Agent 5: Packages .whl artifact → S3 → triggers Airflow DAG."""

    def __init__(self) -> None:
        self.settings = get_settings()

    async def __call__(self, state: GraphState) -> dict[str, Any]:
        try:
            return await self.run(state)
        except Exception as e:
            logger.error("deploy_agent_call_failed", error=str(e))
            return {"error_message": str(e), "status": RunStatus.DONE}

    async def run(self, state: GraphState) -> dict[str, Any]:
        etl_spec = state["etl_spec"]
        logger.info("deploy_agent_started", pipeline=etl_spec.pipeline_name)

        try:
            aws = AWSTools(
                aws_access_key_id=self.settings.aws_access_key_id,
                aws_secret_access_key=self.settings.aws_secret_access_key,
                region=self.settings.aws_region,
                endpoint_url=self.settings.aws_endpoint_url,
            )

            # Step 1: Package .whl (React tool loop — retries on build errors)
            whl_path = await self.react_tool_loop(
                action=lambda: aws.package_whl(
                    pipeline_name=etl_spec.pipeline_name,
                    pipeline_code=state["generated_code"],
                ),
                max_attempts=3,
                errors_to_catch=(Exception,),
                agent_name="deploy_agent",
                action_name="package_whl",
            )

            # Step 2: Upload to S3 (React tool loop — retries on transient S3 errors)
            s3_key = f"artifacts/{etl_spec.pipeline_name}/{etl_spec.pipeline_name}.whl"
            s3_url = await self.react_tool_loop(
                action=lambda: aws.upload_to_s3(
                    local_path=whl_path,
                    bucket=self.settings.aws_s3_artifacts_bucket,
                    key=s3_key,
                ),
                max_attempts=3,
                errors_to_catch=(S3UploadError, Exception),
                agent_name="deploy_agent",
                action_name="upload_to_s3",
            )
            logger.info("artifact_uploaded", s3_url=s3_url)

            # Step 3: Trigger Airflow (skipped when airflow_enabled=false in config)
            dag_run_id: str | None = None
            if self.settings.airflow_enabled:
                user_story = state.get("user_story")
                story_id = user_story.id if user_story else "unknown"
                dag_run_id = await self.react_tool_loop(
                    action=lambda: self._trigger_airflow(
                        etl_spec.pipeline_name, s3_url, str(state["run_id"]), story_id
                    ),
                    max_attempts=3,
                    errors_to_catch=(AirflowTriggerError, Exception),
                    agent_name="deploy_agent",
                    action_name="trigger_airflow",
                )
                logger.info("airflow_triggered", dag_run_id=dag_run_id)
            else:
                logger.info(
                    "airflow_skipped",
                    reason="airflow_enabled=false in config; set AIRFLOW_ENABLED=true to enable",
                )

            return {
                "s3_artifact_url": s3_url,
                "airflow_dag_run_id": dag_run_id,
                "status": RunStatus.DONE,
            }

        except Exception as e:
            logger.error("deploy_agent_failed", error=str(e))
            return {"error_message": str(e), "status": RunStatus.DONE}  # Non-blocking

    async def _trigger_airflow(
        self, pipeline_name: str, artifact_url: str, run_id: str, story_id: str
    ) -> str:
        import httpx

        url = f"{self.settings.airflow_api_url}/api/v1/dags/{self.settings.airflow_dag_id}/dagRuns"
        dag_run_id = f"etl-agent-{run_id}"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json={
                    "dag_run_id": dag_run_id,
                    "conf": {
                        "artifact_url": artifact_url,
                        "pipeline_name": pipeline_name,
                        "run_id": run_id,
                        "story_id": story_id,
                    },
                },
                auth=(self.settings.airflow_username, self.settings.airflow_password),
                timeout=30,
            )
            if response.status_code not in (200, 409):
                raise AirflowTriggerError(
                    f"Airflow API returned {response.status_code}: {response.text}"
                )
            response_data = response.json()
            return response_data.get("dag_run_id", dag_run_id)
