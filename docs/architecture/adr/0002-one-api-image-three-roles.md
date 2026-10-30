# ADR 0002: One API image runs the API, the worker and the CLI

## Status

Accepted.

## Context

The backend has three jobs: answer HTTP requests, execute runs from the queue, and perform
operator tasks (migrations, account creation, demo data, the OpenAPI export). They share
the models, the repositories, the engine and the configuration. The web app has to be
deployed to several environments whose API addresses differ.

## Decision

- `infra/docker/api.Dockerfile` builds one image with three entry points:
  `uvicorn agentstudio.main:create_app --factory` (the default command), `python -m
  agentstudio.worker`, and the `agentstudio` CLI (`migrate`, `user create`, `demo seed`,
  `openapi`).
- Compose runs the same image as `api`, `worker` and a one-shot `migrate`; on AWS the same
  image backs the API service, the worker service and one-off CLI tasks
  (`scripts/aws-run-task.sh`).
- The web app is a second image. It reads its configuration at request time from
  `/env.js` (`window.__AGENTSTUDIO__`), so one build serves local, staging and production.
- Both images are multi-stage, run as a non-root user under `tini`, carry a health check
  and work with a read-only root filesystem.

## Consequences

Positive:

- The API and the worker can never run different versions of the engine or the schema.
- Two images to build, scan and promote, whatever the number of environments.
- Operator tasks run with exactly the production code and configuration.

Trade-offs:

- The worker image carries the web server dependencies and the API carries the worker's;
  the size cost is small next to the shared Python runtime.
- Scaling is per service, not per image, so the ECS services and compose services name the
  role explicitly.

## Alternatives considered

- **Separate API and worker images.** Smaller images, but two build pipelines and a real
  risk of version skew between the process that queues a run and the one that executes it.
- **Build-time configuration for the web app** (`NEXT_PUBLIC_*`). Simpler code, but one
  image per environment, which defeats promoting the image that was tested.
