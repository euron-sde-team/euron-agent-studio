# Deploy to AWS

This guide deploys a complete environment with one command: network, keys, database, cache,
queue, storage, the web app, the API, the workers and monitoring. Two environments ship with
the repository: `aws-dev` (a cheaper full copy) and `aws-prod`. Both call the same module,
`infra/terraform/modules/deployment`, with different sizes and safety switches.

After deployment you have:

| URL | What |
| --- | --- |
| `https://app.<domain>` | The web app |
| `https://api.<domain>` | The API (interactive reference at `/docs`), live traces, webhooks |

## What gets created

| Area | Resources |
| --- | --- |
| Network | A VPC with public and private subnets in two (dev) or three (prod) zones, NAT (one, or one per zone), flow logs, and in prod interface endpoints for AWS APIs |
| Keys and secrets | One customer-managed KMS key with rotation; Secrets Manager entries for `SESSION_SECRET`, `API_KEY_PEPPER`, `ENCRYPTION_KEY` (generated) and `REDIS_URL` |
| Data | RDS PostgreSQL 16 (password managed by RDS, TLS enforced, Multi-AZ in prod), ElastiCache Valkey with TLS and an auth token (a replica in prod), the knowledge bucket (private, versioned, SSE-KMS), the run queue with its dead-letter queue |
| Compute | ECR repositories (immutable tags, scan on push), an ECS cluster with three Fargate services (`web`, `api`, `worker`) on ARM64, autoscaling on CPU, and a task definition for one-off CLI tasks |
| Edge | An Application Load Balancer routing `app.` and `api.` by host, an ACM certificate, DNS records, HTTP redirected to HTTPS, and in prod a WAF |
| Monitoring | CloudWatch log groups, alarms to an SNS topic (optionally e-mailed) and a dashboard |

| Switch | `aws-dev` | `aws-prod` |
| --- | --- | --- |
| Zones, NAT gateways | 2, one shared | 3, one per zone |
| Interface endpoints | off | on |
| Database | single zone, 3 days of backups | Multi-AZ, 14 days, deletion protection |
| Cache replicas | 0 | 1 (automatic failover) |
| WAF | off | on |
| Tasks (min to max) | api 1 to 2, worker 1 to 2, web 1 to 2 | api 2 to 6, worker 2 to 8, web 2 to 6 |
| Log retention | 14 days | 365 days |

## Prerequisites

| Requirement | Notes |
| --- | --- |
| An AWS account and credentials | With permission to create the resources above; the deploy runs as you |
| Terraform 1.10 or later | `versions.tf` requires `>= 1.10.0`, the AWS provider `~> 6.70` and `random ~> 3.9` |
| Docker with `buildx` | Images are built for `linux/arm64` |
| AWS CLI v2 | ECR login, waiting for services, one-off tasks |
| `python3` | Used by the scripts to read Terraform output |
| A domain | The app is served at `app.<domain>` and the API at `api.<domain>` |

Use the same region in your shell as in `terraform.tfvars`:

```bash
export AWS_REGION=us-east-1
```

## 1. Configure the environment

```bash
cp infra/terraform/envs/aws-dev/terraform.tfvars.example infra/terraform/envs/aws-dev/terraform.tfvars
```

`terraform.tfvars` is git-ignored. Variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `region` | `us-east-1` | AWS region |
| `name_prefix` | `agentstudio-dev` / `agentstudio-prod` | Prefix for every resource name; the bucket name derives from it, so make it globally unique (for example `acme-agentstudio-dev`) |
| `domain` | required | Parent domain, for example `agents.example.com` |
| `route53_zone_id` | `null` | Hosted zone for the domain: the certificate is validated and the DNS records are created automatically |
| `certificate_arn` | `null` | An issued ACM certificate for `app.<domain>` and `api.<domain>`, when the zone is not in Route53 |
| `alarm_email` | `null` | Address subscribed to the alarm topic (confirm the subscription e-mail) |
| `product_name` | `Euron AgentStudio` | Name shown in the web app |
| `default_model` | `offline` | Model new Prompt and Agent steps start with |
| `extra_environment` | `{}` | Extra plain environment for the API and workers, for example `{ OPENAI_BASE_URL = "https://api.openai.com/v1" }` |
| `provider_secret_arns` | `{}` | Model provider keys from Secrets Manager, for example `{ OPENAI_API_KEY = "<secret arn>:OPENAI_API_KEY::" }` |
| `http_allowed_hosts` | `[]` | Internal host names HTTP request steps may reach despite the private-network block |
| `http_egress_ports` | `[80]` | TCP ports besides 443 that HTTP request steps may reach on the internet |
| `db_instance_class` | `db.t4g.medium` / `db.r7g.large` | RDS instance class |
| `cache_node_type` | `cache.t4g.small` / `cache.r7g.large` | ElastiCache node type |
| `image_tag` | set by `make aws-deploy` | Image tag; set it here only to pin a release for manual `terraform` runs |

Minimal example:

```hcl
name_prefix     = "acme-agentstudio-dev"
domain          = "agents.example.com"
route53_zone_id = "<ROUTE53_HOSTED_ZONE_ID>"
alarm_email     = "oncall@example.com"
```

`extra_environment` is for configuration, never secrets: values land in the task definitions
in plain text. Put provider keys in Secrets Manager and reference them through
`provider_secret_arns`, which ECS injects at start.

**Without a Route53 zone**, request and validate an ACM certificate for `app.<domain>` and
`api.<domain>` yourself, set `certificate_arn`, and after the deploy point both names at the
`load_balancer_dns_name` output (CNAME or alias).

### Remote state

State contains the generated application secrets. For anything shared, keep it in S3:

```bash
cp infra/terraform/envs/aws-dev/backend.tf.example infra/terraform/envs/aws-dev/backend.tf
```

Uncomment the block and fill in a bucket that is private, versioned and encrypted, with
access limited to the people who deploy. It uses S3-native locking (`use_lockfile = true`),
so no DynamoDB table is needed.

## 2. Deploy

```bash
make aws-deploy ENV=aws-dev
```

`ENV` defaults to `aws-dev`; `TAG` defaults to the first 12 characters of the current commit.
The target runs `scripts/aws-deploy.sh <env> <tag>`, which:

1. checks that `terraform`, `docker` and `aws` are installed and `terraform.tfvars` exists,
   and notes uncommitted changes (images are built from the working tree as it is);
2. **registries**: `terraform apply -target=module.agentstudio.module.ecr`;
3. logs Docker in to ECR;
4. **images**: builds `api` and `web` for `linux/arm64` from `infra/docker/*.Dockerfile` and
   pushes `<repo>:<tag>`;
5. **infrastructure**: `terraform apply` of everything else with that `image_tag`;
6. **rollout**: `aws ecs wait services-stable` for the `api`, `worker` and `web` services;
7. prints the `urls` output and the next step.

Database migrations run when the API boots (`MIGRATE_ON_BOOT=true`) under a Postgres advisory
lock, so several tasks starting together are safe. To run them as an explicit step:

```bash
make aws-migrate ENV=aws-dev
```

To preview changes without applying:

```bash
make aws-plan ENV=aws-dev
```

## 3. Create the first account

Until the first account exists, the sign-up page accepts exactly one sign-up, so create it
right after deploying. From your machine, as a one-off ECS task:

```bash
make aws-cli ENV=aws-dev ARGS="user create --email you@example.com --name 'Your Name' --admin"
```

With no terminal attached, the command generates a temporary password and prints it in the
task's log (which the target tails for you). Sign in at `https://app.<domain>`, then change
it at once: account menu, **Change password**. Create your workspace, and add people under
**Settings, Members**.

## 4. Use a hosted model (optional)

The offline model works with no key. To add an OpenAI-compatible provider:

1. Store the key in Secrets Manager (with the default `aws/secretsmanager` key, or the
   deployment's own KMS key; the task execution role can decrypt either):

   ```bash
   aws secretsmanager create-secret --name acme-agentstudio-dev/models \
     --secret-string '{"OPENAI_API_KEY": "sk-..."}'
   ```

2. Reference it and the endpoint in `terraform.tfvars`:

   ```hcl
   extra_environment    = { OPENAI_BASE_URL = "https://api.openai.com/v1" }
   provider_secret_arns = { OPENAI_API_KEY = "<secret arn>:OPENAI_API_KEY::" }
   default_model        = "openai:gpt-4o-mini"
   ```

3. `make aws-deploy ENV=aws-dev`.

## Updating

Run `make aws-deploy` again from the new commit. Images get a new tag; ECS starts the new
tasks next to the old ones, moves traffic once they pass their health checks, and rolls back
on its own if they never do. Stopping workers let in-flight runs finish for 90 seconds, then
hand the rest back to the queue (ECS waits 120 seconds before it kills a worker), and those
runs resume on the new tasks from their last finished step.

To roll back, apply the previous tag without rebuilding (tags are immutable, so the images
are still in ECR):

```bash
terraform -chdir=infra/terraform/envs/aws-dev apply -var image_tag=<previous tag>
```

Keep migrations additive (add first, remove a release later), so the previous image still
works against the newer schema; that is what makes a rollback a tag change.

## Tearing down

```bash
terraform -chdir=infra/terraform/envs/aws-dev destroy
```

In `aws-prod`, turn off deletion protection first (it guards the database and the load
balancer) and empty the versioned knowledge bucket. The KMS key and the secrets enter their
deletion and recovery windows (30 days in prod, 7 and 0 in dev) instead of disappearing at
once.

## Security notes

- The tasks run in private subnets with no public IPs, as non-root users with read-only root
  filesystems; only the load balancer is public, and it answers `/metrics` with 404.
- `make tf-security` (checkov) passes with every skip justified inline.
- See [security.md](../architecture/security.md#operator-checklist) for the operator checklist
  and [operations.md](operations.md) for day-two tasks: alarms, scaling, rotation, backups.
