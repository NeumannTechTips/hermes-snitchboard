<div align="center">

<img src="docs/assets/banner.svg"
     alt="Hermes Snitchboard: tamper-evident outbound connection audit for Hermes Agent, shown as a sample connection log with allow, beacon, novel and deny entries"
     width="860">

**A dashboard plugin for [Hermes Agent](https://github.com/NousResearch/hermes-agent) that turns
[OpenSnitch](https://github.com/evilsocket/opensnitch) connection evidence into a plain-language,
tamper-evident view of what your machine really connected to.**

[![Status](https://img.shields.io/badge/status-pre--alpha-critical)](#-project-status)
[![Hermes Agent](https://img.shields.io/badge/hermes--agent-%3E%3D0.23.0-1F5FBF)](#-requirements)
[![Platform](https://img.shields.io/badge/platform-Linux-lightgrey)](#-requirements)
[![Runtime dependencies](https://img.shields.io/badge/runtime%20dependencies-none-brightgreen)](#-conventions)
[![Telemetry](https://img.shields.io/badge/telemetry-none-00897B)](#-what-it-will-not-do)
[![Commits](https://img.shields.io/badge/commits-signed-brightgreen)](#-conventions)
[![Licence](https://img.shields.io/badge/licence-MIT%20OR%20Apache--2.0-blue)](#-licence)

Maintained by **[NeumannTechTips](https://github.com/NeumannTechTips)** &middot; Requirements version 1.0 &middot; Reviewed: November 2026

`#HermesAgent` `#OpenSnitch` `#MITREATTACK` `#EgressMonitoring` `#AgenticAI` `#AIGovernance` `#Linux` `#SecurityTooling` `#TamperEvident` `#Observability` `#ZeroTelemetry` `#Python`

</div>

---

> ⚠️ **This is an unofficial, community-built plugin.** It is not affiliated with, endorsed by, or supported by Nous Research or by the OpenSnitch project. Hermes Agent and OpenSnitch are separate projects with their own licences and maintainers.

---

## 📖 Table of contents

- [Project status](#-project-status)
- [Why this exists](#-why-this-exists)
- [How it works](#-how-it-works)
- [What you will see](#-what-you-will-see)
- [What it will not do](#-what-it-will-not-do)
- [Repository map](#-repository-map)
- [Documentation](#-documentation)
- [Requirements](#-requirements)
- [Installation](#-installation)
- [Roadmap](#-roadmap)
- [Conventions](#-conventions)
- [Contributing](#-contributing)
- [Licence](#-licence)
- [Acknowledgements](#-acknowledgements)
- [References](#-references)

---

## 🚦 Project status

**Pre-alpha. There is nothing to install yet.** The requirements are written and signed off, and the build has not started.

> 💡 **What this README is.** It describes intended behaviour rather than shipped behaviour. Each section will be revised as its part is built and tested, and the status badge changes only when a release is tagged.

---

## 🎯 Why this exists

Hermes Agent can run commands, call tools and reach the network on your behalf. The agent can tell you what it did, and application-level tooling can record which model requests it made. Neither tells you what your machine actually connected to, nor whether the record of it has been altered since.

OpenSnitch already sees every outbound connection and the process behind it. That evidence is detailed, but it sits in a database few people read. Hermes Snitchboard presents it inside the Hermes dashboard: what is new, what repeats like a heartbeat, what belongs to AI tooling, and how each finding maps to MITRE ATT&CK. Every stored run is hash-chained to the one before it, so an edited record becomes detectable.

> 💡 **The distinction worth holding onto.** Application-layer tooling records what the agent says it sent. Hermes Snitchboard records what the operating system observed leaving.

---

## 🧭 How it works

Two parts, kept apart on purpose.

```
 OpenSnitch statistics database        read-only, your own account
            |
            v
 collector/snitchboard_collect.py      optional, run by you, never by Hermes
            |   one JSON run record per collection, hash-chained
            v
 runs directory
            |
            v
 dashboard/plugin_api.py (GET only) -> Hermes Snitchboard tab in the dashboard
```

The component inside the dashboard reads run records from one configured directory and nothing else. It never opens the firewall database. That keeps its privileges small, and it suits setups where Hermes runs under a different account from the person who owns the machine.

Until you have collected real runs, the tab shows clearly labelled demonstration data, so every panel is visible without installing OpenSnitch.

---

## 🖥️ What you will see

| Panel | Content |
|---|---|
| 📊 **Summary** | Connections, denials, unique processes and destinations, AI traffic, unattributed traffic |
| ⏱️ **Coverage** | One slot per hour, with gaps shown as gaps |
| 🛡️ **Findings** | Severity, confidence, ATT&CK technique and tactic, the literal records behind each finding, and a concrete next step |
| 📡 **Beacons** | Regular-interval destinations, each with both the benign and the malicious explanation |
| ✨ **Novel destinations** | Addresses never seen before, ranked by rarity |
| 🤖 **Agents** | Activity by AI process and by configured account |
| 📈 **Chart** | Connections per collection across the retained window |
| 🔗 **Integrity** | Run hashes, chain position, and a control that recomputes every link |

Addresses and names are masked by default, with a deliberate control to reveal them.

---

## 🚫 What it will not do

> ⚠️ These are design limits, not gaps awaiting a later release.

| Limit | Why |
|---|---|
| 🔒 Never blocks, allows or changes anything on the host | It observes and reports. Enforcement belongs to the firewall |
| 🔐 Never decrypts or describes traffic content | Connections are events with byte counts where measured, never payloads |
| 📴 Makes no network call and sends no telemetry | The plugin opens no socket and loads no external font, script or image |
| 🗝️ Reads no credential store | No `.env`, no `auth.json`, no browser profile, no key store |
| ⚖️ Does not prove what the network did | The hash chain makes alteration detectable. Someone able to rewrite every record could recompute it |

---

## 🗺️ Repository map

| Path | Contents | State |
|---|---|---|
| `docs` | Requirements, banner and its generator | ✅ Populated |
| `snitchboard` | Analysis engine: schema, canonical hashing, analysis, redaction | 🚧 Not started |
| `dashboard` | Manifest, read-only API routes, and the tab bundle | 🚧 Not started |
| `collector` | Reference collector and its systemd user timer templates | 🚧 Not started |
| `fixtures` | Synthetic demonstration records, documentation ranges only | 🚧 Not started |
| `tools` | Demonstration generator and repository scan scripts | 🚧 Not started |
| `tests` | Unit tests for every analysis rule and the integrity chain | 🚧 Not started |
| `.github/workflows` | Tests, plugin validation, history and fixture scans | 🚧 Not started |

---

## 📚 Documentation

| Document | What it gives you |
|---|---|
| [`docs/HSB-PRD-001-Product-Requirements.md`](docs/HSB-PRD-001-Product-Requirements.md) | Problem, success criteria, scope, design, analysis rules, security and privacy requirements, build plan, risks and the decisions taken |

A reference architecture diagram is drafted and will be added once it is finalised.

> ⚠️ **The requirements govern.** When a decision changes, revise the requirements document first. Code follows from it, never the reverse.

---

## ⚙️ Requirements

| Requirement | Detail |
|---|---|
| Hermes Agent | v0.23.0 or later, with the web dashboard |
| Operating system | Linux |
| OpenSnitch | Needed only for live data. Demonstration mode needs nothing else |
| Python packages | None. The engine uses the standard library alone |

---

## 📦 Installation

Not yet available. Instructions will be added once the plugin passes `hermes plugins validate` and is submitted to the Hermes plugin catalogue.

---

## 🛣️ Roadmap

| Stage | Work | State |
|---|---|---|
| Requirements | Problem, scope, design, analysis rules and plan | ✅ Signed off |
| Core | Run record schema, canonical hashing, analysis engine, tests | 🚧 Not started |
| Dashboard | Backend routes and the tab, with demonstration data | 🚧 Not started |
| Collector | Reference script for the OpenSnitch statistics database | 🚧 Not started |
| Release | Validation, screenshots, catalogue submission | 🚧 Not started |

---

## 🔧 Conventions

| Item | Setting |
|---|---|
| Default branch | `main` |
| Commit signing | SSH, enabled globally. Commits show as Verified on GitHub |
| Commit messages | Imperative mood, describing the change rather than the file touched |
| Sign-off | Every commit carries a `Signed-off-by` line under the [Developer Certificate of Origin](https://developercertificate.org/) |
| Runtime dependencies | None. Anything beyond the standard library needs a recorded decision |
| Committed artefacts | Source only. No compiled binary, no bytecode, no minified bundle |
| Demonstration data | Synthetic, inside the ranges reserved by [RFC 5737](https://www.rfc-editor.org/rfc/rfc5737), [RFC 3849](https://www.rfc-editor.org/rfc/rfc3849) and [RFC 2606](https://www.rfc-editor.org/rfc/rfc2606) |
| Language | Professional British English throughout |

> 🚫 **Never committed:** real capture data, OpenSnitch databases, run records from a live host, credentials, or any address, hostname or path belonging to a real machine. The [`.gitignore`](.gitignore) enforces these patterns as a safety net rather than as a substitute for checking `git status`.

---

## 🤝 Contributing

Guidelines will be published with the first tagged release. Until the core is built, an issue describing the problem you want solved is more useful than a pull request.

---

## 📄 Licence

Dual licensed under either of:

- MIT licence ([LICENSE-MIT](LICENSE-MIT) or <https://opensource.org/licenses/MIT>)
- Apache Licence, Version 2.0 ([LICENSE-APACHE](LICENSE-APACHE) or <https://www.apache.org/licenses/LICENSE-2.0>)

at your option. Unless you state otherwise, any contribution you intentionally submit for inclusion in this work is dual licensed on the same terms, with no additional conditions.

Hermes Agent and OpenSnitch are separate projects and neither is redistributed here.

---

## 🙏 Acknowledgements

Built for [Hermes Agent](https://github.com/NousResearch/hermes-agent) by [Nous Research](https://nousresearch.com), using the evidence that [OpenSnitch](https://github.com/evilsocket/opensnitch) collects. Findings are mapped to [MITRE ATT&CK](https://attack.mitre.org/).

The avatar set in the banner is the Nous Research character mark, which also ships in the Hermes Agent repository under `assets/`. It appears here as a visual nod to the project this plugin is built for, and it carries no suggestion of endorsement. The notice at the head of this document governs.

---

## 🔗 References

- [Hermes Agent, extending the dashboard](https://hermes-agent.nousresearch.com/docs/user-guide/features/extending-the-dashboard)
- [Hermes Agent, plugin developer guide](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins)
- [Hermes Agent, submitting to the plugin catalogue](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins/catalog-submission)
- [OpenSnitch](https://github.com/evilsocket/opensnitch)
- [MITRE ATT&CK](https://attack.mitre.org/)

---

<div align="center">

**Unofficial community plugin &middot; [NeumannTechTips](https://github.com/NeumannTechTips)**

</div>
