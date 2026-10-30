# -----------------------------------------------------------------------------
# One complete AgentStudio deployment: network, keys, data, cache, queue and services.
#
#   https://app.<domain>   web app (flow editor, run traces, approvals, knowledge)
#   https://api.<domain>   API (interactive reference at /docs), live traces, webhooks
#   workers                long-poll the run queue and execute flows
#
# envs/aws-dev and envs/aws-prod call this module with different sizes and safety
# switches; everything else is identical by construction.
# -----------------------------------------------------------------------------
data "aws_region" "current" {}

locals {
  region    = data.aws_region.current.region
  hostnames = { app = "app.${var.domain}", api = "api.${var.domain}" }
  urls      = { for k, h in local.hostnames : k => "https://${h}" }
  images    = { for k, url in module.ecr.repository_urls : k => "${url}:${var.image_tag}" }
  run_queue = "${var.name_prefix}-runs"
}

# --- Foundation --------------------------------------------------------------

module "network" {
  source                     = "../network"
  name_prefix                = var.name_prefix
  cidr_block                 = var.vpc_cidr
  az_count                   = var.az_count
  single_nat_gateway         = var.single_nat_gateway
  enable_interface_endpoints = var.enable_interface_endpoints
  flow_log_retention_days    = var.flow_log_retention_days
  logs_kms_key_arn           = module.kms.key_arn
}

# Data at rest: knowledge bucket, run queue, database, cache, secrets, logs.
module "kms" {
  source                  = "../kms"
  name_prefix             = var.name_prefix
  description             = "${var.name_prefix}: knowledge files, run queue, database, cache, secrets and logs at rest"
  deletion_window_in_days = var.kms_deletion_window_days
  admin_principal_arns    = var.kms_admin_principal_arns
}

module "secrets" {
  source                  = "../secrets"
  name_prefix             = var.name_prefix
  kms_key_arn             = module.kms.key_arn
  recovery_window_in_days = var.secret_recovery_window_days
}

module "database" {
  source                = "../database"
  name_prefix           = var.name_prefix
  vpc_id                = module.network.vpc_id
  subnet_ids            = module.network.private_subnet_ids
  kms_key_arn           = module.kms.key_arn
  instance_class        = var.db_instance_class
  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = var.db_max_allocated_storage
  multi_az              = var.db_multi_az
  backup_retention_days = var.db_backup_retention_days
  deletion_protection   = var.deletion_protection
  skip_final_snapshot   = !var.deletion_protection
  monitoring_interval   = var.db_monitoring_interval
}

module "storage" {
  source            = "../storage"
  name_prefix       = var.name_prefix
  kms_key_arn       = module.kms.key_arn
  enable_versioning = true
  force_destroy     = !var.deletion_protection
}

module "queues" {
  source      = "../queues"
  names       = [local.run_queue]
  kms_key_arn = module.kms.key_arn
}

module "cache" {
  source                  = "../cache"
  name_prefix             = var.name_prefix
  vpc_id                  = module.network.vpc_id
  subnet_ids              = module.network.private_subnet_ids
  kms_key_arn             = module.kms.key_arn
  node_type               = var.cache_node_type
  replicas                = var.cache_replicas
  apply_immediately       = !var.deletion_protection
  recovery_window_in_days = var.secret_recovery_window_days
}

module "ecr" {
  source       = "../ecr"
  name_prefix  = var.name_prefix
  repositories = ["api", "web"]
  kms_key_arn  = module.kms.key_arn
  force_delete = !var.deletion_protection
}

# --- Edge --------------------------------------------------------------------

module "edge" {
  source              = "../edge"
  name_prefix         = var.name_prefix
  vpc_id              = module.network.vpc_id
  public_subnet_ids   = module.network.public_subnet_ids
  hostnames           = local.hostnames
  route53_zone_id     = var.route53_zone_id
  certificate_arn     = var.certificate_arn
  access_logs_bucket  = var.alb_access_logs_bucket
  enable_waf          = var.enable_waf
  deletion_protection = var.deletion_protection
}

resource "aws_ecs_cluster" "this" {
  name = var.name_prefix
  setting {
    name  = "containerInsights"
    value = "enhanced"
  }
}

# --- Shared application configuration ----------------------------------------

locals {
  app_environment = merge({
    APP_ENV         = "production"
    LOG_FORMAT      = "json"
    PRODUCT_NAME    = var.product_name
    AWS_REGION      = local.region
    CORS_ORIGINS    = local.urls.app
    WEB_URL         = local.urls.app
    PUBLIC_API_URL  = local.urls.api
    COOKIE_SECURE   = "true"
    STORAGE_BACKEND = "s3"
    S3_BUCKET       = module.storage.bucket_name
    S3_KMS_KEY_ID   = module.kms.key_arn
    QUEUE_BACKEND   = "sqs"
    SQS_QUEUE_URL   = module.queues.queue_urls[local.run_queue]
    # No password in the environment: the app reads it from the RDS-managed secret for
    # each new connection, so a rotation needs no redeploy.
    DATABASE_URL        = "postgresql+asyncpg://${module.database.master_username}@${module.database.address}:${module.database.port}/${module.database.database_name}?ssl=require"
    DATABASE_SECRET_ARN = module.database.master_user_secret_arn
    MIGRATE_ON_BOOT     = tostring(var.migrate_on_boot)
    # Trust X-Forwarded-For only from inside the VPC (the load balancer), so per-address
    # limits (sign-in) see the real client and not whatever a client claims to be.
    FORWARDED_ALLOW_IPS = module.network.vpc_cidr_block
    DEFAULT_MODEL       = var.default_model
    # HTTP request steps may call public endpoints only; list internal hosts to allow them.
    HTTP_ALLOWED_HOSTS = join(",", var.http_allowed_hosts)
  }, var.extra_environment)

  app_secrets = concat(
    [for k in module.secrets.keys : { name = k, valueFrom = "${module.secrets.secret_arn}:${k}::" }],
    [{ name = "REDIS_URL", valueFrom = "${module.cache.url_secret_arn}:REDIS_URL::" }],
    [for name, arn in var.provider_secret_arns : { name = name, valueFrom = arn }],
  )
}

# What both the API (uploads, enqueueing runs, inline runs for ?wait) and the workers (every
# run) do at runtime: read the database password, read and write knowledge originals, and
# send, receive and delete run messages.
data "aws_iam_policy_document" "runtime" {
  statement {
    sid       = "DatabasePassword"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [module.database.master_user_secret_arn]
  }
  statement {
    sid       = "DecryptViaServices"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [module.kms.key_arn]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values = [
        "s3.${local.region}.amazonaws.com",
        "sqs.${local.region}.amazonaws.com",
        "secretsmanager.${local.region}.amazonaws.com",
      ]
    }
  }
  statement {
    sid       = "KnowledgeFiles"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${module.storage.bucket_arn}/workspaces/*"]
  }
  statement {
    sid       = "KnowledgeBucket"
    actions   = ["s3:ListBucket"]
    resources = [module.storage.bucket_arn]
  }
  statement {
    sid = "RunQueue"
    actions = [
      "sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage",
      "sqs:ChangeMessageVisibility", "sqs:GetQueueAttributes", "sqs:GetQueueUrl",
    ]
    resources = module.queues.queue_arns
  }
}

locals {
  python_health = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/livez', timeout=3)\""]
  worker_health = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:9100/metrics', timeout=3)\""]
}

# --- Services ----------------------------------------------------------------

module "api" {
  source                   = "../service"
  name_prefix              = var.name_prefix
  name                     = "api"
  image                    = local.images.api
  environment              = local.app_environment
  secrets                  = local.app_secrets
  cluster_arn              = aws_ecs_cluster.this.arn
  vpc_id                   = module.network.vpc_id
  subnet_ids               = module.network.private_subnet_ids
  listener_arn             = module.edge.https_listener_arn
  lb_security_group_id     = module.edge.security_group_id
  listener_priority        = 100
  host_headers             = [local.hostnames.api]
  internal_paths           = ["/metrics", "/metrics/*"]
  health_check_path        = "/livez"
  extra_egress_ports       = var.http_egress_ports
  connect_to_database      = true
  db_security_group_id     = module.database.security_group_id
  db_port                  = module.database.port
  connect_to_cache         = true
  cache_security_group_id  = module.cache.security_group_id
  kms_key_arn              = module.kms.key_arn
  has_task_policy          = true
  task_policy_json         = data.aws_iam_policy_document.runtime.json
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  min_count                = var.api_min_count
  max_count                = var.api_max_count
  log_retention_days       = var.log_retention_days
  logs_kms_key_arn         = module.kms.key_arn
  container_health_command = local.python_health
}

# Workers long-poll the run queue; one at a time (elected through Valkey) also re-queues
# runs whose worker vanished and expires approvals past their deadline.
module "worker" {
  source                  = "../service"
  name_prefix             = var.name_prefix
  name                    = "worker"
  image                   = local.images.api
  command                 = ["python", "-m", "agentstudio.worker"]
  environment             = merge(local.app_environment, { WORKER_CONCURRENCY = tostring(var.worker_concurrency), WORKER_METRICS_PORT = "9100" })
  secrets                 = local.app_secrets
  attach_to_load_balancer = false
  cluster_arn             = aws_ecs_cluster.this.arn
  vpc_id                  = module.network.vpc_id
  subnet_ids              = module.network.private_subnet_ids
  extra_egress_ports      = var.http_egress_ports
  connect_to_database     = true
  db_security_group_id    = module.database.security_group_id
  db_port                 = module.database.port
  connect_to_cache        = true
  cache_security_group_id = module.cache.security_group_id
  kms_key_arn             = module.kms.key_arn
  has_task_policy         = true
  task_policy_json        = data.aws_iam_policy_document.runtime.json
  cpu                     = var.worker_cpu
  memory                  = var.worker_memory
  min_count               = var.worker_min_count
  max_count               = var.worker_max_count
  log_retention_days      = var.log_retention_days
  logs_kms_key_arn        = module.kms.key_arn
  # A worker serves no traffic; the container check reads its metrics endpoint.
  container_health_command = local.worker_health
}

# One-off tasks on the API image: migrations and accounts (make aws-cli).
module "cli" {
  source                  = "../service"
  name_prefix             = var.name_prefix
  name                    = "cli"
  image                   = local.images.api
  command                 = ["agentstudio", "--help"]
  environment             = local.app_environment
  secrets                 = local.app_secrets
  create_service          = false
  cluster_arn             = aws_ecs_cluster.this.arn
  vpc_id                  = module.network.vpc_id
  subnet_ids              = module.network.private_subnet_ids
  connect_to_database     = true
  db_security_group_id    = module.database.security_group_id
  db_port                 = module.database.port
  connect_to_cache        = true
  cache_security_group_id = module.cache.security_group_id
  kms_key_arn             = module.kms.key_arn
  has_task_policy         = true
  task_policy_json        = data.aws_iam_policy_document.runtime.json
  cpu                     = 512
  memory                  = 1024
  log_retention_days      = var.log_retention_days
  logs_kms_key_arn        = module.kms.key_arn
}

module "web" {
  source               = "../service"
  name_prefix          = var.name_prefix
  name                 = "web"
  image                = local.images.web
  environment          = { API_URL = local.urls.api, PRODUCT_NAME = var.product_name, PORT = "8080", HOSTNAME = "0.0.0.0" }
  cluster_arn          = aws_ecs_cluster.this.arn
  vpc_id               = module.network.vpc_id
  subnet_ids           = module.network.private_subnet_ids
  listener_arn         = module.edge.https_listener_arn
  lb_security_group_id = module.edge.security_group_id
  listener_priority    = 110
  host_headers         = [local.hostnames.app]
  health_check_path    = "/env.js"
  kms_key_arn          = module.kms.key_arn
  cpu                  = var.web_cpu
  memory               = var.web_memory
  min_count            = var.web_min_count
  max_count            = var.web_max_count
  log_retention_days   = var.log_retention_days
  logs_kms_key_arn     = module.kms.key_arn
}

# --- Observability -----------------------------------------------------------

module "observability" {
  source                     = "../observability"
  name_prefix                = var.name_prefix
  alarm_email                = var.alarm_email
  alb_arn_suffix             = module.edge.arn_suffix
  ecs_cluster_name           = aws_ecs_cluster.this.name
  db_instance_identifier     = module.database.instance_identifier
  worker_service_name        = module.worker.service_name
  run_queue_name             = local.run_queue
  run_dead_letter_queue_name = module.queues.dlq_names[local.run_queue]
  services = {
    api    = module.api.service_name
    worker = module.worker.service_name
    web    = module.web.service_name
  }
  target_groups = {
    api = module.api.target_group_arn_suffix
    web = module.web.target_group_arn_suffix
  }
}
