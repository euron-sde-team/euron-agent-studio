# Full CI pipeline (opt-in)

These workflows are the complete quality pipeline for Euron AgentStudio. They are kept here,
outside `.github/workflows/`, so they do **not** run on the upstream repository. Only the fast
[`checks`](../workflows/checks.yml) workflow (lint, typecheck, unit tests, Terraform
validation, the sanitization scan) runs there.

| Workflow | What it runs |
| --- | --- |
| [`ci.yml`](ci.yml) | Lint, typecheck, unit tests, the web build, the OpenAPI document check, the sanitization scan, then the API integration suite on PostgreSQL 16, Valkey 8 and Floci |
| [`security.yml`](security.yml) | gitleaks over the full history, CodeQL (Python, JavaScript and TypeScript), `pnpm audit` and `pip-audit` |
| [`terraform.yml`](terraform.yml) | `terraform fmt` and `validate` for every environment, tflint, checkov |
| [`docker.yml`](docker.yml) | Multi-architecture image builds for `api` and `web`, pushed to GHCR on version tags |
| [`e2e.yml`](e2e.yml) | The full stack on the Floci emulator with demo data, then the Playwright end-to-end suite and the QA crawl |

To enable them in your fork, move them into `.github/workflows/`:

```bash
git mv .github/workflows-full/*.yml .github/workflows/
```

Every gate is also runnable locally:
`make lint typecheck test test-integration e2e qa sanitize tf-fmt tf-validate tf-lint tf-security`.
