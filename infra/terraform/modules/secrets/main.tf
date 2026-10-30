# Application secrets, generated once and stored in Secrets Manager. ECS injects each JSON
# key into the API and worker containers as an environment variable; the values never
# appear in a task definition, a Terraform plan output or a log.
#
#   SESSION_SECRET   signs session tokens; rotating it signs everyone out
#   API_KEY_PEPPER   keys the API key hashes; rotating it invalidates every API key
#   ENCRYPTION_KEY   AES-256-GCM key for workspace secrets and webhook signing secrets
#
# The first two are distinct on purpose (production refuses to boot if they are equal), so
# an operator can rotate either without the other.
resource "random_password" "this" {
  for_each = toset(["SESSION_SECRET", "API_KEY_PEPPER"])
  length   = 64
  special  = false
}

resource "random_bytes" "encryption_key" {
  length = 32
}

resource "aws_secretsmanager_secret" "app" {
  #checkov:skip=CKV2_AWS_57:These are signing and encryption keys; rotation is an operator procedure (docs/guides/operations.md), not a Lambda.
  name                    = "${var.name_prefix}/app"
  description             = "AgentStudio session secret, API key pepper and encryption key"
  kms_key_id              = var.kms_key_arn
  recovery_window_in_days = var.recovery_window_in_days
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode(merge(
    { for k, v in random_password.this : k => v.result },
    { ENCRYPTION_KEY = random_bytes.encryption_key.base64 },
  ))

  # Rotation happens out of band (put a new version by hand or by pipeline). Without
  # this, the next `terraform apply` would quietly roll every secret back.
  lifecycle {
    ignore_changes = [secret_string]
  }
}
