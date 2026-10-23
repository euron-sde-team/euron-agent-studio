# Security Policy

## Supported versions

| Version | Supported |
| ------- | --------- |
| 0.x (latest minor) | Yes |
| Older minors | No |

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately through GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on this repository ("Security" tab, "Report a vulnerability").

Please include:

- the affected component (`apps/api`, `apps/web`, `infra/terraform/...`) and version or commit,
- a description of the issue and its impact,
- steps to reproduce, or a proof of concept,
- any suggested mitigation.

What to expect:

| Stage | Target |
| ----- | ------ |
| Acknowledgement | within 3 business days |
| Initial assessment and severity | within 7 business days |
| Fix or mitigation for critical and high issues | within 30 days |
| Coordinated public disclosure | after a fix is released, credited to you unless you prefer otherwise |

## Scope

In scope: the code in this repository and the infrastructure it provisions with its
default settings. The most important classes of issue for this project are:

- **Crossing a workspace boundary**: reading or running another workspace's flows, runs,
  approvals, knowledge bases or secrets.
- **Server-side request forgery** through the HTTP Request node or webhook handling, for
  example reaching cloud metadata endpoints or private addresses the deployment does not allow.
- **Secret disclosure**: a workspace secret appearing in a run trace, an export, a log line or
  an API response.
- **Code injection through export**: a flow whose names, prompts or settings make the
  generated Python script run something other than the flow.
- **Webhook forgery or replay**: starting a run without the signing secret, or replaying a
  signed request outside its window.

Out of scope:

- **What a workspace member can already do.** Editors design flows that call models and
  HTTP endpoints by design; viewers read every run in their workspace.
- **Instructions planted in your own inputs or documents.** A model may follow text written
  into a ticket or a knowledge document you supplied. No prompt is a security boundary;
  reports where such text crosses into another workspace or reveals secrets are in scope.
- **The demo seed.** `make demo` creates well-known demo passwords on purpose and refuses to
  run with `APP_ENV=production`.
- Findings that require a compromised host, compromised AWS account, or leaked deployment
  secrets.
- Denial of service through resource exhaustion of a deployment you operate yourself.

## Hardening checklist for operators

See [docs/architecture/security.md](docs/architecture/security.md#operator-checklist).
