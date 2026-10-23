<p align="center">
  <img src="docs/assets/banner.svg" alt="Euron AgentStudio: build agent workflows on a canvas, watch every run live, export any flow as a Python script" width="100%">
</p>

<p align="center">
  <img alt="Open source" src="https://img.shields.io/badge/open_source-%E2%9D%A4-f97316?style=flat">
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-3b82f6?style=flat"></a>
  <img alt="Python 3.12" src="https://img.shields.io/badge/python-3.12-3776ab?style=flat&logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-async-009688?style=flat&logo=fastapi&logoColor=white">
  <img alt="Next.js" src="https://img.shields.io/badge/Next.js-App_Router-000000?style=flat&logo=nextdotjs&logoColor=white">
  <img alt="PostgreSQL 16" src="https://img.shields.io/badge/PostgreSQL-16-4169e1?style=flat&logo=postgresql&logoColor=white">
  <img alt="Redis 7" src="https://img.shields.io/badge/Redis-7-dc382d?style=flat&logo=redis&logoColor=white">
  <img alt="Terraform" src="https://img.shields.io/badge/IaC-Terraform-7b42bc?style=flat&logo=terraform&logoColor=white">
  <img alt="AWS" src="https://img.shields.io/badge/AWS-ready-ff9900?style=flat&logo=amazonwebservices&logoColor=white">
</p>

<p align="center">
  <a href="https://github.com/euron-sde-team/euron-agent-studio/stargazers"><img alt="Star this repo" src="https://img.shields.io/github/stars/euron-sde-team/euron-agent-studio?style=social&label=Star%20this%20repo"></a>
  <a href="https://github.com/euron-sde-team/euron-agent-studio/fork"><img alt="Fork" src="https://img.shields.io/github/forks/euron-sde-team/euron-agent-studio?style=social&label=Fork"></a>
  <a href="https://github.com/euron-sde-team/euron-agent-studio/watchers"><img alt="Watch" src="https://img.shields.io/github/watchers/euron-sde-team/euron-agent-studio?style=social&label=Watch"></a>
  <br>
  <a href="https://github.com/euron-sde-team/euron-agent-studio/issues"><img alt="Open issues" src="https://img.shields.io/github/issues/euron-sde-team/euron-agent-studio?style=flat&color=f97316"></a>
  <a href="https://github.com/euron-sde-team/euron-agent-studio/pulls"><img alt="PRs welcome" src="https://img.shields.io/badge/PRs-welcome-34d399?style=flat"></a>
  <a href="https://github.com/euron-sde-team/euron-agent-studio/commits/main"><img alt="Last commit" src="https://img.shields.io/github/last-commit/euron-sde-team/euron-agent-studio?style=flat&color=8b95a8"></a>
  <img alt="Runs offline with no API key" src="https://img.shields.io/badge/runs_offline-no_API_key_needed-1c1410?style=flat">
  <br>
  <a href="#built-by-the-team-behind-euron"><img alt="Built by the team behind Euron" src="https://img.shields.io/badge/built_by-Euron-4f46e5?style=flat"></a>
</p>

<p align="center">
  <b><a href="docs/architecture/HLD.md">Architecture</a></b> &middot;
  <b><a href="docs/architecture/LLD.md">Design</a></b> &middot;
  <b><a href="docs/architecture/data-model.md">Data model</a></b> &middot;
  <b><a href="SECURITY.md">Security</a></b> &middot;
  <b><a href="CONTRIBUTING.md">Contributing</a></b>
</p>

**Euron AgentStudio** is an open-source, MIT-licensed builder for AI agent workflows, part of
the open-source initiative of **ENGAGESPHERE TECHNOLOGY PRIVATE LIMITED**. Draw a flow on a
canvas (prompts, agents with tools, HTTP calls, knowledge search, conditions, loops and human
approvals), run it from the UI, the API or a signed webhook, watch every step stream its
inputs, outputs, latency, tokens and cost live, and export the flow as a standalone Python
script that reproduces it with `httpx`.

> [!NOTE]
> Every flow, test and demo runs offline: AgentStudio ships a deterministic model provider
> that needs no API key, and the AWS services it uses (SQS, S3, KMS, Secrets Manager) run on
> an emulator provisioned by the same Terraform that builds production.

<h3 align="center">Built by the team behind Euron</h3>

<p align="center">Euron AgentStudio comes from the people who build these platforms. If you like how this repository is built, come and see what we build with it.</p>

<p align="center">
  <a href="https://euron.one"><picture><source media="(prefers-color-scheme: dark)" srcset="docs/assets/brand/euron-dark.svg"><img src="docs/assets/brand/euron-light.svg" alt="Euron: learn the latest technologies from industry experts. Visit euron.one" width="31%"></picture></a>
  <a href="https://euronsystems.com"><picture><source media="(prefers-color-scheme: dark)" srcset="docs/assets/brand/euron-systems-dark.svg"><img src="docs/assets/brand/euron-systems-light.svg" alt="Euron Systems: the SaaS platform for educators and creators. Visit euronsystems.com" width="31%"></picture></a>
  <a href="https://alphaeuron.com"><picture><source media="(prefers-color-scheme: dark)" srcset="docs/assets/brand/alpha-euron-dark.svg"><img src="docs/assets/brand/alpha-euron-light.svg" alt="Alpha Euron: where school kids grow creativity and tech skills with AI. Visit alphaeuron.com" width="31%"></picture></a>
</p>

<p align="center">
  <a href="https://www.instagram.com/euron_official"><img src="https://img.shields.io/badge/Instagram-E4405F?style=flat-square&logo=instagram&logoColor=white" alt="Instagram"></a>
  <a href="https://www.linkedin.com/company/euronone/posts/"><img src="https://img.shields.io/badge/LinkedIn-0A66C2?style=flat-square&logo=linkedin&logoColor=white" alt="LinkedIn"></a>
  <a href="https://x.com/euron712"><img src="https://img.shields.io/badge/X-000000?style=flat-square&logo=x&logoColor=white" alt="X"></a>
  <a href="https://www.youtube.com/@Euron-official"><img src="https://img.shields.io/badge/YouTube-FF0000?style=flat-square&logo=youtube&logoColor=white" alt="YouTube"></a>
  <a href="https://whatsapp.com/channel/0029VaeeJwq9RZAfPW9P2l07"><img src="https://img.shields.io/badge/WhatsApp_channel-25D366?style=flat-square&logo=whatsapp&logoColor=white" alt="WhatsApp channel"></a>
</p>

---

## Documentation

- [High-level design](docs/architecture/HLD.md): the product, the system and how a run travels.
- [Low-level design](docs/architecture/LLD.md): the graph format, node types, the engine, the exporter and the API.
- [Data model](docs/architecture/data-model.md): tables, indexes, Redis keys and queue messages.

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 ENGAGESPHERE TECHNOLOGY
PRIVATE LIMITED and the Euron AgentStudio contributors.
