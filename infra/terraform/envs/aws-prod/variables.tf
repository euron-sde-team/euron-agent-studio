variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "name_prefix" {
  description = "Prefix for every resource name."
  type        = string
  default     = "agentstudio-prod"
}

variable "domain" {
  description = "Parent domain: the app is served at app.<domain> and the API at api.<domain>."
  type        = string
}

variable "route53_zone_id" {
  description = "Hosted zone for the domain. Null: publish the DNS records from the outputs yourself."
  type        = string
  default     = null
}

variable "certificate_arn" {
  description = "Existing ACM certificate for app.<domain> and api.<domain>. Null requests one."
  type        = string
  default     = null
}

variable "product_name" {
  description = "Name shown in the web app."
  type        = string
  default     = "Euron AgentStudio"
}

variable "image_tag" {
  description = "Image tag to deploy (make aws-deploy passes the git commit)."
  type        = string
  default     = "latest"
}

variable "default_model" {
  description = "Model new Prompt and Agent steps start with: offline, or a configured provider's model."
  type        = string
  default     = "offline"
}

variable "provider_secret_arns" {
  description = "Model provider keys from Secrets Manager, e.g. { OPENAI_API_KEY = \"<secret arn>:OPENAI_API_KEY::\" }."
  type        = map(string)
  default     = {}
}

variable "extra_environment" {
  description = "Additional environment for the API and workers, e.g. { OPENAI_BASE_URL = \"https://api.openai.com/v1\" }."
  type        = map(string)
  default     = {}
}

variable "http_egress_ports" {
  description = "TCP ports besides 443 that HTTP request steps may reach on the internet."
  type        = list(number)
  default     = [80]
}

variable "http_allowed_hosts" {
  description = "Internal host names HTTP request steps may reach despite the private-network block."
  type        = list(string)
  default     = []
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.r7g.large"
}

variable "cache_node_type" {
  description = "ElastiCache node type."
  type        = string
  default     = "cache.r7g.large"
}

variable "alarm_email" {
  description = "Address that receives alarm notifications."
  type        = string
  default     = null
}
