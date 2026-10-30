# Euron AgentStudio: developer entry points. `make` lists every target.
SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

COMPOSE_DIR := deploy/compose
FLOCI       := docker compose --env-file "$(COMPOSE_DIR)/.env" -f "$(COMPOSE_DIR)/compose.yaml" -f "$(COMPOSE_DIR)/compose.floci.yaml"
AWS_LOCAL   := docker compose --env-file "$(COMPOSE_DIR)/.env" -f "$(COMPOSE_DIR)/compose.yaml" -f "$(COMPOSE_DIR)/compose.aws.yaml"
API         := uv --directory apps/api run
TF_IMAGE    := hashicorp/terraform:1.16.6
TF_ENVS     := local-floci aws-dev aws-prod
# Use a local terraform when installed, otherwise the pinned container. The container writes
# each environment's .terraform directory into the (git-ignored) working tree, so `init` and
# `validate` can run as separate containers.
ifeq ($(shell command -v terraform),)
TF          := docker run --rm -v "$(CURDIR)/infra/terraform:/infra" -v agentstudio-tf-plugins:/plugins -e TF_PLUGIN_CACHE_DIR=/plugins -w /infra $(TF_IMAGE)
TF_ROOT     := /infra
else
TF          := terraform
TF_ROOT     := infra/terraform
endif
# The browser suites sign in as the demo accounts seeded by `make demo`.
DEMO_PASSWORD = $(shell grep -s '^AGENTSTUDIO_DEMO_PASSWORD=' "$(COMPOSE_DIR)/.env" | cut -d= -f2)
ENV         ?= aws-dev
TAG         ?= $(shell git rev-parse --short=12 HEAD 2>/dev/null || echo dev)

.PHONY: help env up up-aws down logs ps demo test test-integration test-deps-down e2e qa \
        screenshots lint format typecheck build openapi sanitize tf-fmt tf-validate tf-lint \
        tf-security aws-plan aws-deploy aws-migrate aws-cli clean

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage: make \033[36m<target>\033[0m\n\n"} /^[a-zA-Z0-9_-]+:.*##/ { printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

# --- Local -------------------------------------------------------------------

env: ## Generate deploy/compose/.env with random local-only secrets
	@scripts/gen-local-env.sh

up: env ## Start everything on emulated AWS (Floci), provisioned by the same Terraform as production
	$(FLOCI) up -d --build --wait
	@echo ""
	@echo "  web        http://localhost:$${AGENTSTUDIO_WEB_PORT:-3120}"
	@echo "  api        http://localhost:$${AGENTSTUDIO_API_PORT:-8120}/docs"
	@echo "  worker     http://localhost:$${AGENTSTUDIO_WORKER_METRICS_PORT:-9120}/metrics"
	@echo ""
	@echo "  Next: make demo   (accounts, six flows from the templates, two weeks of real runs)"

up-aws: env ## Start the stack against real AWS resources (needs deploy/compose/.env.aws)
	@test -f "$(COMPOSE_DIR)/.env.aws" || { echo "copy $(COMPOSE_DIR)/.env.aws.example to .env.aws first"; exit 1; }
	$(AWS_LOCAL) up -d --build --wait

demo: ## Seed the Northwind workspace with flows and real run history (prints the logins)
	$(FLOCI) exec -T -e DEMO_PASSWORD=$(DEMO_PASSWORD) api agentstudio demo seed
	@echo "  password:  $(DEMO_PASSWORD)   (AGENTSTUDIO_DEMO_PASSWORD in deploy/compose/.env)"

down: ## Stop the stack and delete its volumes
	-$(FLOCI) down -v --remove-orphans
	-$(AWS_LOCAL) down -v --remove-orphans 2>/dev/null

logs: ## Tail logs (SERVICE=api|worker|web|migrate|postgres|valkey|floci|terraform)
	$(FLOCI) logs -f --tail 100 $(SERVICE)

ps: ## Show stack status
	$(FLOCI) ps

# --- Quality -----------------------------------------------------------------

lint: ## Lint and check formatting (ruff, ESLint, Prettier)
	$(API) ruff check . && $(API) ruff format --check .
	pnpm lint
	pnpm format:check

format: ## Format every file (ruff, Prettier)
	$(API) ruff check --fix . && $(API) ruff format .
	pnpm format

typecheck: ## Typecheck (mypy strict, tsc)
	$(API) mypy
	pnpm typecheck

test: ## Unit tests (pytest, Vitest)
	$(API) pytest tests/unit -q
	pnpm test

test-integration: ## API integration tests against real Postgres, Valkey and Floci (started if needed)
	@scripts/test-deps.sh up >/dev/null
	$(API) pytest tests/integration -q

test-deps-down: ## Stop the integration test services
	@scripts/test-deps.sh down

e2e: ## Browser end-to-end tests (Playwright) against the running stack (make up demo first)
	DEMO_PASSWORD=$(DEMO_PASSWORD) pnpm e2e

qa: ## Crawl every page at desktop and mobile widths; fails on console errors and axe violations
	DEMO_PASSWORD=$(DEMO_PASSWORD) pnpm qa

screenshots: ## README screenshots (1440x900 @2x) and docs/assets/tour.gif from the running stack
	DEMO_PASSWORD=$(DEMO_PASSWORD) pnpm capture

build: ## Build the web app and both images
	pnpm build
	docker build -f infra/docker/api.Dockerfile -t agentstudio-api:local .
	docker build -f infra/docker/web.Dockerfile -t agentstudio-web:local .

openapi: ## Regenerate docs/api/openapi.json from the routes
	$(API) agentstudio openapi --out ../../docs/api/openapi.json

sanitize: ## Scan committable files for credentials and cloud identifiers
	@scripts/check-sanitization.sh

# --- Terraform ---------------------------------------------------------------

tf-fmt: ## Format all Terraform
	$(TF) fmt -recursive $(TF_ROOT)

tf-validate: ## terraform validate every environment (no backend, no credentials)
	@for env in $(TF_ENVS); do \
	  echo "== $$env"; \
	  $(TF) -chdir=$(TF_ROOT)/envs/$$env init -backend=false -input=false -no-color >/dev/null && \
	  $(TF) -chdir=$(TF_ROOT)/envs/$$env validate -no-color || exit 1; \
	done

tf-lint: ## tflint every module and environment (plugins cached in a docker volume)
	docker run --rm -v "$(CURDIR)/infra/terraform:/data" -v agentstudio-tflint:/plugins -e TFLINT_PLUGIN_DIR=/plugins -w /data ghcr.io/terraform-linters/tflint:v0.64.0 --init
	docker run --rm -v "$(CURDIR)/infra/terraform:/data" -v agentstudio-tflint:/plugins -e TFLINT_PLUGIN_DIR=/plugins -w /data ghcr.io/terraform-linters/tflint:v0.64.0 --recursive --format compact

tf-security: ## checkov policy scan of the Terraform (any unskipped finding fails)
	docker run --rm -v "$(CURDIR)/infra/terraform:/tf" bridgecrew/checkov:3.3.30 -d /tf --framework terraform --quiet --compact --config-file /tf/.checkov.yaml

# --- AWS ---------------------------------------------------------------------

aws-plan: ## terraform plan for ENV (aws-dev | aws-prod); needs terraform.tfvars and AWS credentials
	cd "infra/terraform/envs/$(ENV)" && terraform init -input=false && terraform plan -var image_tag=$(TAG)

aws-deploy: ## One shot: registries, images, infrastructure, rollout (ENV=aws-dev|aws-prod)
	@scripts/aws-deploy.sh $(ENV) $(TAG)

aws-migrate: ## Run database migrations as a one-off ECS task (ENV=...)
	@scripts/aws-run-task.sh $(ENV) agentstudio migrate

aws-cli: ## Any agentstudio CLI command as a one-off ECS task (ENV=... ARGS="user create --email ...")
	@test -n "$(ARGS)" || { echo 'usage: make aws-cli ARGS="user create --email you@example.com --name You --admin"'; exit 1; }
	@scripts/aws-run-task.sh $(ENV) agentstudio $(ARGS)

clean: ## Remove build output and caches
	rm -rf apps/web/.next e2e/test-results e2e/playwright-report e2e/.qa e2e/.auth e2e/.capture apps/api/.pytest_cache apps/api/.mypy_cache apps/api/.ruff_cache
