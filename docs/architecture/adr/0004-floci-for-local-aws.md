# ADR 0004: Develop against the Floci AWS emulator, provisioned by the production Terraform

## Status

Accepted.

## Context

On AWS the API and the worker depend on SQS (the run queue and its dead-letter queue), S3
(knowledge documents, encrypted with KMS), KMS and Secrets Manager. Local development that
swapped each of these for something else (an in-process queue, files on disk) would leave
the queue semantics that the engine's reliability depends on (visibility timeouts,
redelivery, dead-lettering) untested until a real AWS account. The infrastructure code also
needs a place to run on every change without credentials.

## Decision

- `make up` runs the Floci AWS emulator (`floci/floci:2.3.0`, MIT licence) next to
  Postgres and Valkey (`deploy/compose/compose.floci.yaml`).
- A one-shot Terraform container (`hashicorp/terraform:1.16.6`) applies
  `infra/terraform/envs/local-floci` to the emulator before the migrations, the API and the
  worker start. That environment uses the same `kms`, `storage`, `queues` and `secrets`
  modules as AWS, with only the endpoints and a few emulator switches changed (plain HTTP,
  so no TLS-only bucket policy; versioning off; force-destroy on).
- The API and the worker run with `STORAGE_BACKEND=s3` and `QUEUE_BACKEND=sqs`, pointed at
  the emulator through `AWS_ENDPOINT_URL`. The bucket is
  `agentstudio-local-knowledge` (SSE-KMS with `alias/agentstudio-local`), the queue
  `agentstudio-local-runs` with its dead-letter queue.
- The integration tests start their own Floci (`scripts/test-deps.sh`, port 9123) and
  exercise S3 uploads and the SQS worker path against it: duplicates, lost workers, lost
  messages and graceful hand-back.
- The local backends (`STORAGE_BACKEND=local`, `QUEUE_BACKEND=inline`) remain for unit-level
  work; production refuses both.

## Consequences

Positive:

- Developers and CI exercise the real AWS SDK calls, SSE-KMS uploads and SQS redelivery
  without an AWS account or any cost.
- The Terraform modules are applied on every `make up`, not only on deploy.

Trade-offs:

- An emulator is not AWS: IAM policy evaluation, quotas and some timing are not reproduced.
  `make up-aws` (compose against real AWS resources) and the `aws-dev` environment cover the
  gap ([deploy-aws.md](../../guides/deploy-aws.md)).
- One more container and image version to keep current.

## Alternatives considered

- **Per-service substitutes** (MinIO, ElasticMQ, an in-process queue). Each is good at one
  service, but together they are more moving parts than one emulator, and none of them runs
  the production Terraform.
- **LocalStack.** A comparable emulator; Floci is the one this workspace standardises on
  across its projects.
- **A shared development AWS account.** Highest fidelity, but it needs credentials for
  every contributor, costs money, and shared state makes tests interfere with each other.
