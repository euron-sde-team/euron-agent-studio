output "bucket_name" {
  description = "Knowledge bucket name (S3_BUCKET)."
  value       = aws_s3_bucket.this.bucket
}

output "bucket_arn" {
  description = "Knowledge bucket ARN, for IAM policies."
  value       = aws_s3_bucket.this.arn
}
