# Run locally against real AWS

`make up` runs everything against the Floci emulator. When you need the real services (real
KMS key policies, real IAM, a real bucket and queue), run the same local containers with the
AWS overlay instead. PostgreSQL, Valkey and the web app still run locally; S3, KMS and SQS
are the real services in your account.

## How it works

`make up-aws` combines `deploy/compose/compose.yaml` with `deploy/compose/compose.aws.yaml`.
The overlay:

- loads `deploy/compose/.env.aws` into the `migrate`, `api` and `worker` containers
  (`STORAGE_BACKEND=s3`, `QUEUE_BACKEND=sqs` and the resource names);
- mounts your `~/.aws` directory read-only and selects `AWS_PROFILE` (default `default`), so
  the SDK uses your normal credentials;
- does not start the emulator and sets no endpoint override.

## 1. Have the AWS resources

| Resource | Requirement |
| --- | --- |
| S3 bucket | Private; SSE-KMS with the key below |
| KMS key | Symmetric; usable by your identity for S3 and SQS (`kms:GenerateDataKey`, `kms:Decrypt`) |
| SQS queue | A standard queue with a dead-letter queue, **used by nothing else** |

Do not point the local stack at a queue that deployed workers read: they would receive the
local runs' messages, find no such run in their own database, and delete them, so local
runs would never start. Create a separate queue for local work.

An `aws-dev` deployment ([deploy-aws.md](deploy-aws.md)) gives you the bucket
(`<name_prefix>-knowledge`) and the key (`alias/<name_prefix>`); its key policy delegates to
IAM, so an identity with the right IAM permissions can use it. Create the queue yourself, for
example:

```bash
aws sqs create-queue --queue-name agentstudio-local-dlq
aws sqs create-queue --queue-name agentstudio-local-runs --attributes '{
  "VisibilityTimeout": "300",
  "RedrivePolicy": "{\"deadLetterTargetArn\":\"arn:aws:sqs:us-east-1:<account>:agentstudio-local-dlq\",\"maxReceiveCount\":\"10\"}"
}'
```

Your IAM identity needs roughly what the runtime task role has: `s3:GetObject`,
`s3:PutObject` and `s3:DeleteObject` on `<bucket>/workspaces/*`, `s3:ListBucket` on the
bucket, `sqs:SendMessage`, `sqs:ReceiveMessage`, `sqs:DeleteMessage`,
`sqs:ChangeMessageVisibility` and `sqs:GetQueueAttributes` on the queue, and the KMS
permissions above.

## 2. Write `.env.aws`

```bash
cp deploy/compose/.env.aws.example deploy/compose/.env.aws
```

Edit it:

```bash
AWS_REGION=us-east-1
STORAGE_BACKEND=s3
S3_BUCKET=acme-agentstudio-dev-knowledge
S3_KMS_KEY_ID=alias/acme-agentstudio-dev
QUEUE_BACKEND=sqs
SQS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/<account>/agentstudio-local-runs
```

The file holds resource names only, never credentials. To use a named profile, set it in
your shell: `export AWS_PROFILE=agentstudio-dev`.

## 3. Start

```bash
make up-aws
```

The URLs are the same as with `make up` (web 3120, API 8120). `make demo` targets the
emulator overlay, so seed the demo data with the AWS overlay's file list:

```bash
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml -f deploy/compose/compose.aws.yaml \
  exec -T -e DEMO_PASSWORD="$(grep AGENTSTUDIO_DEMO_PASSWORD deploy/compose/.env | cut -d= -f2)" api agentstudio demo seed
```

Check readiness: `curl -s localhost:8120/readyz` reports `storage` and `queue` as `ok` when
the bucket and the queue are reachable with your credentials; `failing` names the one that
is not (the API log says why).

## What is different from the emulator

| Area | Behaviour against real AWS |
| --- | --- |
| Knowledge files | Stored in your bucket under `workspaces/<workspace id>/`, encrypted with your key |
| Run queue | Real visibility timeouts, redelivery and dead-lettering, with real latency |
| Permissions | Real IAM evaluation: a missing permission fails here, as it would on ECS |
| Cost | You pay for S3 storage and requests, SQS requests and KMS requests |

## Stop

```bash
make down
```

`make down` stops both overlays and deletes the local volumes (the database). Objects in
your bucket stay in AWS; delete the knowledge bases in the app before you reset, or empty
the `workspaces/` prefix afterwards.
