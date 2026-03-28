# =============================================================================
# SQS — story pipeline queue + dead-letter queue
#
# Visibility timeout = 900 s (15 min) — matches Lambda's max and gives a
# pipeline run the full time before the message becomes visible again.
#
# After 3 failed receive attempts the message moves to the DLQ for
# manual inspection / replay.
# =============================================================================

resource "aws_sqs_queue" "pipeline_dlq" {
  name                      = "${var.project_name}-pipeline-dlq"
  message_retention_seconds = 1209600  # 14 days
  kms_master_key_id         = "alias/aws/sqs"

  tags = { Project = var.project_name, Purpose = "dead-letter" }
}

resource "aws_sqs_queue" "pipeline" {
  name                       = "${var.project_name}-pipeline"
  visibility_timeout_seconds = 900
  message_retention_seconds  = 86400   # 1 day — runs should complete well within this
  max_message_size           = 262144  # 256 KB — story JSON is always < 32 KB
  receive_wait_time_seconds  = 20      # long-polling reduces empty receives
  kms_master_key_id          = "alias/aws/sqs"

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.pipeline_dlq.arn
    maxReceiveCount     = 3
  })

  tags = { Project = var.project_name, Purpose = "pipeline-intake" }
}

# ─── Queue policy — allow ECS task role to send + receive ────────────────────

resource "aws_sqs_queue_policy" "pipeline" {
  queue_url = aws_sqs_queue.pipeline.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowECSTaskRole"
        Effect    = "Allow"
        Principal = { AWS = aws_iam_role.ecs_task.arn }
        Action    = [
          "sqs:SendMessage",
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:ChangeMessageVisibility",
        ]
        Resource = aws_sqs_queue.pipeline.arn
      }
    ]
  })
}

resource "aws_sqs_queue_policy" "pipeline_dlq" {
  queue_url = aws_sqs_queue.pipeline_dlq.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowECSTaskRoleDLQ"
        Effect    = "Allow"
        Principal = { AWS = aws_iam_role.ecs_task.arn }
        Action    = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
        ]
        Resource = aws_sqs_queue.pipeline_dlq.arn
      }
    ]
  })
}

# ─── CloudWatch alarm — DLQ not empty ────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "dlq_not_empty" {
  alarm_name          = "${var.project_name}-dlq-messages"
  alarm_description   = "One or more pipeline runs failed and landed in the DLQ"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.pipeline_dlq.name
  }

  alarm_actions = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
  ok_actions    = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []

  tags = { Project = var.project_name }
}
