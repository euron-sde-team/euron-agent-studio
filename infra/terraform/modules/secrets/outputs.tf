output "secret_arn" {
  description = "ARN of the JSON secret holding SESSION_SECRET, API_KEY_PEPPER and ENCRYPTION_KEY."
  value       = aws_secretsmanager_secret.app.arn
}

output "keys" {
  description = "JSON keys inside the secret, for ECS `secrets` valueFrom references."
  value       = ["API_KEY_PEPPER", "ENCRYPTION_KEY", "SESSION_SECRET"]
}
