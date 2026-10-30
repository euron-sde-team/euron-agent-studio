# -----------------------------------------------------------------------------
# aws-dev: a full, cheaper copy of production. Two zones, one NAT gateway,
# a single-AZ database, no cache replica and no deletion protection.
#
# Everything is in ../../modules/deployment; this file only picks the sizes.
#   make aws-deploy ENV=aws-dev
# -----------------------------------------------------------------------------
module "agentstudio" {
  source = "../../modules/deployment"

  name_prefix     = var.name_prefix
  domain          = var.domain
  route53_zone_id = var.route53_zone_id
  certificate_arn = var.certificate_arn
  product_name    = var.product_name
  image_tag       = var.image_tag

  default_model        = var.default_model
  provider_secret_arns = var.provider_secret_arns
  extra_environment    = var.extra_environment
  http_egress_ports    = var.http_egress_ports
  http_allowed_hosts   = var.http_allowed_hosts

  az_count                   = 2
  single_nat_gateway         = true
  enable_interface_endpoints = false

  db_instance_class        = var.db_instance_class
  db_multi_az              = false
  db_backup_retention_days = 3
  deletion_protection      = false

  cache_node_type = var.cache_node_type
  cache_replicas  = 0

  enable_waf = false

  kms_deletion_window_days    = 7
  secret_recovery_window_days = 0

  api_min_count    = 1
  api_max_count    = 2
  worker_min_count = 1
  worker_max_count = 2
  web_min_count    = 1
  web_max_count    = 2

  log_retention_days = 14
  alarm_email        = var.alarm_email
}
