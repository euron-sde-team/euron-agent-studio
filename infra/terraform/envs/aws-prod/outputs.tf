output "urls" {
  description = "Public URLs of the web app and the API."
  value       = module.agentstudio.urls
}

output "ecr_repository_urls" {
  description = "Image repositories."
  value       = module.agentstudio.ecr_repository_urls
}

output "cluster_name" {
  description = "ECS cluster."
  value       = module.agentstudio.cluster_name
}

output "service_names" {
  description = "ECS services."
  value       = module.agentstudio.service_names
}

output "cli_task_definition" {
  description = "Task definition for one-off CLI tasks."
  value       = module.agentstudio.cli_task_definition
}

output "cli_security_group_id" {
  description = "Security group for one-off CLI tasks."
  value       = module.agentstudio.cli_security_group_id
}

output "private_subnet_ids" {
  description = "Private subnets for one-off tasks."
  value       = module.agentstudio.private_subnet_ids
}

output "load_balancer_dns_name" {
  description = "Point app.<domain> and api.<domain> here when the zone is not in Route53."
  value       = module.agentstudio.load_balancer_dns_name
}

output "certificate_validation_records" {
  description = "DNS records to publish when the zone is not in Route53."
  value       = module.agentstudio.certificate_validation_records
}

output "knowledge_bucket" {
  description = "S3_BUCKET, the originals of uploaded knowledge documents."
  value       = module.agentstudio.knowledge_bucket
}

output "run_queue_url" {
  description = "SQS_QUEUE_URL, the run queue."
  value       = module.agentstudio.run_queue_url
}

output "kms_key_alias" {
  description = "The deployment key."
  value       = module.agentstudio.kms_key_alias
}
