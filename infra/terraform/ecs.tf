# =============================================================================
# ECS Fargate — two services:
#   api-service    : FastAPI app  (1–4 tasks, scale on CPU)
#   worker-service : SQS consumer (0–10 tasks, scale on queue depth)
#
# Application Load Balancer sits in front of the API service.
# Both services run from the same Docker image; CMD is overridden per task.
# =============================================================================

locals {
  # Use var.image_tag when supplied (e.g. from CD pipeline: -var image_tag=$GIT_SHA).
  # Fall back to "latest" for manual / first-run applies.
  _image_tag = var.image_tag != "" ? var.image_tag : "latest"
  image_uri  = "${aws_ecr_repository.etl_agent.repository_url}:${local._image_tag}"
}

# ─── CloudWatch Log Groups ────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.project_name}/api"
  retention_in_days = 30
  tags              = { Project = var.project_name }
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/${var.project_name}/worker"
  retention_in_days = 30
  tags              = { Project = var.project_name }
}

# ─── ECS Cluster ─────────────────────────────────────────────────────────────

resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = { Project = var.project_name }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
    base              = 1
  }
}

# ─── Secrets Manager references ───────────────────────────────────────────────

data "aws_secretsmanager_secret" "app_secrets" {
  name = "${var.project_name}/app"
}

# ─── Shared environment variables ─────────────────────────────────────────────

locals {
  common_env = [
    { name = "DATABASE_URL",                    value = "postgresql+asyncpg://${var.db_username}:${var.db_password}@${aws_db_instance.postgres.address}:5432/${var.db_name}" },
    { name = "SQS_QUEUE_URL",                   value = aws_sqs_queue.pipeline.url },
    { name = "SQS_DLQ_URL",                     value = aws_sqs_queue.pipeline_dlq.url },
    { name = "S3_BUCKET",                        value = var.s3_bucket },
    { name = "AWS_REGION",                       value = var.aws_region },
    { name = "CORS_ORIGINS",                     value = var.cors_origins },
    { name = "MAX_TOKENS_PER_RUN",               value = tostring(var.max_tokens_per_run) },
    { name = "BUDGET_APPROVAL_THRESHOLD_PCT",    value = tostring(var.budget_approval_threshold_pct) },
  ]

  common_secrets = [
    { name = "ANTHROPIC_API_KEY", valueFrom = "${data.aws_secretsmanager_secret.app_secrets.arn}:ANTHROPIC_API_KEY::" },
    { name = "API_KEY",           valueFrom = "${data.aws_secretsmanager_secret.app_secrets.arn}:API_KEY::" },
    { name = "GITHUB_TOKEN",      valueFrom = "${data.aws_secretsmanager_secret.app_secrets.arn}:GITHUB_TOKEN::" },
    { name = "DB_PASSWORD",       valueFrom = "${data.aws_secretsmanager_secret.app_secrets.arn}:DB_PASSWORD::" },
  ]
}

# ─── API Task Definition ──────────────────────────────────────────────────────
# Lightweight: FastAPI + middleware. No PySpark. 512 vCPU / 1 GB RAM.

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.project_name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = local.image_uri
      essential = true

      command = ["uvicorn", "etl_agent.api.main:app",
                 "--host", "0.0.0.0", "--port", "8000",
                 "--workers", "2", "--log-level", "info"]

      portMappings = [{ containerPort = 8000, protocol = "tcp" }]

      environment = local.common_env
      secrets     = local.common_secrets

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.api.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "api"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:8000/api/v1/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }

      readonlyRootFilesystem = false
      user                   = "nobody"
    }
  ])

  tags = { Project = var.project_name }
}

# ─── Worker Task Definition ───────────────────────────────────────────────────
# PySpark-heavy: 4 vCPU / 8 GB RAM.
# Runs the SQS consumer loop — one task per in-flight pipeline run.

resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.project_name}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "4096"
  memory                   = "8192"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  # Fargate ephemeral storage — enough for PySpark temp files + code artifacts
  ephemeral_storage {
    size_in_gib = 30
  }

  container_definitions = jsonencode([
    {
      name      = "worker"
      image     = local.image_uri
      essential = true

      command = ["python", "-m", "etl_agent.worker"]

      environment = concat(local.common_env, [
        { name = "WORKER_CONCURRENCY",   value = "1" },
        { name = "SQS_VISIBILITY_TIMEOUT", value = "900" },
        { name = "SQS_MAX_MESSAGES",     value = "1" },
        { name = "JAVA_TOOL_OPTIONS", value = "-Xmx4g -XX:+UseG1GC --add-opens=java.base/java.lang=ALL-UNNAMED --add-opens=java.base/java.lang.invoke=ALL-UNNAMED --add-opens=java.base/java.nio=ALL-UNNAMED --add-opens=java.base/java.util=ALL-UNNAMED --add-opens=java.base/sun.nio.ch=ALL-UNNAMED" },
      ])
      secrets = local.common_secrets

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.worker.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "worker"
        }
      }

      readonlyRootFilesystem = false
      user                   = "nobody"
    }
  ])

  tags = { Project = var.project_name }
}

# ─── Application Load Balancer ────────────────────────────────────────────────

resource "aws_lb" "api" {
  name               = "${var.project_name}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id

  enable_deletion_protection = false
  enable_http2               = true

  # ALB access logs require a dedicated S3 bucket policy granting the
  # regional ELB service account PutObject rights.  Disabled until that
  # policy is added to the bucket; re-enable by setting enabled = true.
  access_logs {
    bucket  = var.s3_bucket
    prefix  = "alb-logs"
    enabled = false
  }

  tags = { Project = var.project_name }
}

resource "aws_lb_target_group" "api" {
  name        = "${var.project_name}-api-tg"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    path                = "/api/v1/health"
    protocol            = "HTTP"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }

  deregistration_delay = 30

  tags = { Project = var.project_name }
}

# HTTP listener — forwards directly when no TLS cert is configured yet.
resource "aws_lb_listener" "http_forward" {
  count = var.acm_certificate_arn == "" ? 1 : 0

  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

# HTTP listener — redirects to HTTPS once a cert is attached.
resource "aws_lb_listener" "http_redirect" {
  count = var.acm_certificate_arn != "" ? 1 : 0

  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# HTTPS listener — only created when an ACM certificate ARN is provided.
resource "aws_lb_listener" "https" {
  count = var.acm_certificate_arn != "" ? 1 : 0

  load_balancer_arn = aws_lb.api.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.acm_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

# ─── API ECS Service ──────────────────────────────────────────────────────────

resource "aws_ecs_service" "api" {
  name                               = "${var.project_name}-api"
  cluster                            = aws_ecs_cluster.main.id
  task_definition                    = aws_ecs_task_definition.api.arn
  desired_count                      = var.api_desired_count
  launch_type                        = "FARGATE"
  platform_version                   = "LATEST"
  health_check_grace_period_seconds  = 60

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  deployment_controller {
    type = "ECS"
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [aws_lb_listener.http_forward, aws_lb_listener.http_redirect]

  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }

  tags = { Project = var.project_name }
}

# ─── Worker ECS Service ───────────────────────────────────────────────────────

resource "aws_ecs_service" "worker" {
  name             = "${var.project_name}-worker"
  cluster          = aws_ecs_cluster.main.id
  task_definition  = aws_ecs_task_definition.worker.arn
  desired_count    = 0   # scales from 0 via KEDA/SQS autoscaling
  launch_type      = "FARGATE"
  platform_version = "LATEST"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }

  tags = { Project = var.project_name }
}

# ─── Auto Scaling — API (CPU-based) ──────────────────────────────────────────

resource "aws_appautoscaling_target" "api" {
  max_capacity       = var.api_max_count
  min_capacity       = var.api_min_count
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.api.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "api_cpu" {
  name               = "${var.project_name}-api-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.api.resource_id
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension
  service_namespace  = aws_appautoscaling_target.api.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = 70.0
    scale_in_cooldown  = 300
    scale_out_cooldown = 60

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}

# ─── Auto Scaling — Worker (SQS queue depth) ─────────────────────────────────

resource "aws_appautoscaling_target" "worker" {
  max_capacity       = var.worker_max_count
  min_capacity       = 0
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.worker.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "worker_sqs" {
  name               = "${var.project_name}-worker-sqs-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.worker.resource_id
  scalable_dimension = aws_appautoscaling_target.worker.scalable_dimension
  service_namespace  = aws_appautoscaling_target.worker.service_namespace

  target_tracking_scaling_policy_configuration {
    # One worker task per message in the queue.
    # Scale to 0 when queue is empty.
    target_value       = 1.0
    scale_in_cooldown  = 120
    scale_out_cooldown = 30

    customized_metric_specification {
      metric_name = "ApproximateNumberOfMessagesVisible"
      namespace   = "AWS/SQS"
      statistic   = "Average"

      dimensions {
        name  = "QueueName"
        value = aws_sqs_queue.pipeline.name
      }
    }
  }
}
