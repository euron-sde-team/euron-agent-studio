output "kms_key_alias" {
  description = "S3_KMS_KEY_ID for the local stack."
  value       = module.kms.alias_name
}

output "knowledge_bucket" {
  description = "S3_BUCKET for the local stack."
  value       = module.storage.bucket_name
}

output "run_queue_url" {
  description = "SQS_QUEUE_URL for the local stack."
  value       = module.queues.queue_urls["${var.name_prefix}-runs"]
}

output "app_secret_arn" {
  description = "The generated application secrets (not read by the local stack)."
  value       = module.secrets.secret_arn
}
