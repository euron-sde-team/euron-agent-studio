variable "endpoint" {
  description = "Emulator endpoint. http://localhost:4612 from the host, http://floci:4566 inside compose."
  type        = string
  default     = "http://localhost:4612"
}

variable "name_prefix" {
  description = "Must match S3_BUCKET, S3_KMS_KEY_ID and SQS_QUEUE_URL in deploy/compose/compose.floci.yaml."
  type        = string
  default     = "agentstudio-local"
}
