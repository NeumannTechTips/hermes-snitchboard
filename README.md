# 🛰️ Hardening a Self-Hosted AI Agent on Signal

> A practitioner's build note on bridging the **Nous Research Hermes Agent** to **Signal** over `signal-cli`, driving authenticated outbound messaging, and reducing the inbound attack surface to a defensible least-privilege posture.

[![Status](https://img.shields.io/badge/status-stable-brightgreen)](#)
[![Platform](https://img.shields.io/badge/platform-Fedora%20KDE-blue)](#)
[![Agent](https://img.shields.io/badge/agent-Hermes-8A2BE2)](#)
[![Transport](https://img.shields.io/badge/messaging-Signal-3A76F0)](#)
[![Threat model](https://img.shields.io/badge/threat%20model-documented-critical)](#)
[![Licence](https://img.shields.io/badge/licence-MIT-lightgrey)](#)

Author: **[NeumannTechTips](https://github.com/NeumannTechTips)** · Reviewed: August 2026

`#Signal` `#signal-cli` `#CyberSecurity` `#AIAgents` `#HermesAgent` `#LeastPrivilege` `#PromptInjection` `#OWASPTop10` `#SelfHosted` `#DevSecOps` `#PrivacyByDesign` `#ThreatModelling` `#journald` `#InfoSec`

---

## 📖 Table of contents

- [Why this exists](#-why-this-exists)
- [What you get](#-what-you-get)
- [Architecture at a glance](#-architecture-at-a-glance)
- [Threat model in brief](#-threat-model-in-brief)
- [Before you start](#-before-you-start)
- [Part 1: Stand up the Signal link](#-part-1-stand-up-the-signal-link)
- [Part 2: Authenticated outbound messaging](#-part-2-authenticated-outbound-messaging)
- [Part 3: Harden the channel](#-part-3-harden-the-channel)
- [Verification](#-verification)
- [Security findings](#-security-findings)
- [Troubleshooting](#-troubleshooting)
- [Lessons learned](#-lessons-learned)
- [Reference](#-reference)
- [Topics](#-topics)
- [Licence](#-licence)

---

## 🤔 Why this exists

Attaching a chat transport to an autonomous agent is a five-minute task. Doing it without opening a remote-code-execution path onto the host is not. The upstream quick-start links the account and moves on; it does not tell you that an inbound message now lands in the context of a process that reads your home directory, holds your model weights, and can drive a shell. In <abbr title="Open Worldwide Application Security Project: the body that publishes the Top 10 lists for web and, now, agentic-AI risks">OWASP</abbr> terms this is textbook **excessive agency** married to an untrusted input surface.

This note documents a build that treats the inbound path as the primary control problem rather than an afterthought. It records what works, corrects two points in the upstream documentation that will otherwise cost you an evening, and states the security decisions plainly enough that you could defend them at a review board.

> 💡 **Tooltip (plain English):** an AI agent that can run commands on your computer is powerful and risky. If a stranger can message it, they might be able to make it run those commands. This guide is about closing that door while keeping the useful part.

The reference host is a Fedora KDE workstation running a locally hosted agent against a local model. The controls generalise to any comparable deployment.

### Key outcomes

- ✅ Authenticated outbound messaging to any contact, addressed in <abbr title="E.164 is the international phone-number format: a plus sign, country code, then the number, with no spaces">E.164</abbr> form
- ✅ No third-party desktop client and no bespoke connector code in the trust path
- ✅ The Signal adapter runs an explicit least-privilege toolset rather than the default full-access profile
- ✅ Every control is reversible, evidenced against source, and greyscale-legible in the architecture view
- ✅ The clear-text logging exposure in the default posture is identified and remediated

---

## 📦 What you get

| Capability | Status | Notes |
|---|---|---|
| Outbound to an arbitrary contact | ✅ Stable | Single first-party command, E.164 addressing, recipient resolved via `listContacts` |
| Inbound from an allow-listed principal | ✅ Stable | Deny-by-default; unknown senders require explicit pairing |
| Per-adapter toolset restriction | ✅ Stable | Verified against the framework's own resolver, not self-reported |
| Clear-text log remediation | ⚠️ Manual | One daemon flag; verify residue afterwards |
| Name-based addressing | 🚧 Deferred | Requires a reviewed contact map; PII trade-off, see closing notes |

---

## 🗺️ Architecture at a glance

The agent never speaks the Signal protocol directly. It drives a local `signal-cli` daemon over a JSON interface bound to the loopback interface, and that daemon attaches to your account as a **linked secondary device** under the Sesame session model. The phone remains the primary registration throughout.

<p align="center">
  <img alt="Hermes Agent on Signal: hardened reference architecture" src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxNzAwIDEwMTAiIGZvbnQtZmFtaWx5PSJTZWdvZSBVSSwgSGVsdmV0aWNhLCBBcmlhbCwgc2Fucy1zZXJpZiI+CiAgPGRlZnM+CiAgICA8bWFya2VyIGlkPSJhU2xhdGUiIG1hcmtlcldpZHRoPSIxMCIgbWFya2VySGVpZ2h0PSI4IiByZWZYPSI4IiByZWZZPSIzIiBvcmllbnQ9ImF1dG8tc3RhcnQtcmV2ZXJzZSIgbWFya2VyVW5pdHM9InN0cm9rZVdpZHRoIj48cGF0aCBkPSJNMCwwIEw4LDMgTDAsNiBaIiBmaWxsPSIjMzQ0OTVFIi8+PC9tYXJrZXI+CiAgICA8bWFya2VyIGlkPSJhVGVhbCIgbWFya2VyV2lkdGg9IjEwIiBtYXJrZXJIZWlnaHQ9IjgiIHJlZlg9IjgiIHJlZlk9IjMiIG9yaWVudD0iYXV0by1zdGFydC1yZXZlcnNlIiBtYXJrZXJVbml0cz0ic3Ryb2tlV2lkdGgiPjxwYXRoIGQ9Ik0wLDAgTDgsMyBMMCw2IFoiIGZpbGw9IiMxRjdBOEMiLz48L21hcmtlcj4KICAgIDxtYXJrZXIgaWQ9ImFHcmVlbiIgbWFya2VyV2lkdGg9IjEwIiBtYXJrZXJIZWlnaHQ9IjgiIHJlZlg9IjgiIHJlZlk9IjMiIG9yaWVudD0iYXV0by1zdGFydC1yZXZlcnNlIiBtYXJrZXJVbml0cz0ic3Ryb2tlV2lkdGgiPjxwYXRoIGQ9Ik0wLDAgTDgsMyBMMCw2IFoiIGZpbGw9IiMyRTdEMzIiLz48L21hcmtlcj4KICAgIDxtYXJrZXIgaWQ9ImFBbWJlciIgbWFya2VyV2lkdGg9IjEwIiBtYXJrZXJIZWlnaHQ9IjgiIHJlZlg9IjgiIHJlZlk9IjMiIG9yaWVudD0iYXV0by1zdGFydC1yZXZlcnNlIiBtYXJrZXJVbml0cz0ic3Ryb2tlV2lkdGgiPjxwYXRoIGQ9Ik0wLDAgTDgsMyBMMCw2IFoiIGZpbGw9IiNFNEExMUIiLz48L21hcmtlcj4KICAgIDxtYXJrZXIgaWQ9ImFSZWQiIG1hcmtlcldpZHRoPSIxMCIgbWFya2VySGVpZ2h0PSI4IiByZWZYPSI4IiByZWZZPSIzIiBvcmllbnQ9ImF1dG8tc3RhcnQtcmV2ZXJzZSIgbWFya2VyVW5pdHM9InN0cm9rZVdpZHRoIj48cGF0aCBkPSJNMCwwIEw4LDMgTDAsNiBaIiBmaWxsPSIjQzAzOTJCIi8+PC9tYXJrZXI+CiAgICA8bWFya2VyIGlkPSJhR3JleSIgbWFya2VyV2lkdGg9IjEwIiBtYXJrZXJIZWlnaHQ9IjgiIHJlZlg9IjgiIHJlZlk9IjMiIG9yaWVudD0iYXV0by1zdGFydC1yZXZlcnNlIiBtYXJrZXJVbml0cz0ic3Ryb2tlV2lkdGgiPjxwYXRoIGQ9Ik0wLDAgTDgsMyBMMCw2IFoiIGZpbGw9IiM2QjdDOEMiLz48L21hcmtlcj4KICA8L2RlZnM+CgogIDxyZWN0IHg9IjAiIHk9IjAiIHdpZHRoPSIxNzAwIiBoZWlnaHQ9IjEwMTAiIGZpbGw9IiNGRkZGRkYiLz4KCiAgPCEtLSBmcmFtaW5nIHBhbmVscyAtLT4KICA8cmVjdCB4PSIyMCIgeT0iMzYwIiB3aWR0aD0iNTI1IiBoZWlnaHQ9IjE4NSIgcng9IjgiIGZpbGw9Im5vbmUiIHN0cm9rZT0iIzhGQTlCQyIgc3Ryb2tlLXdpZHRoPSIxLjIiIHN0cm9rZS1kYXNoYXJyYXk9IjYgNCIvPgogIDx0ZXh0IHg9IjM0IiB5PSIzODAiIGZvbnQtc2l6ZT0iMTIiIGZvbnQtd2VpZ2h0PSJib2xkIiBmaWxsPSIjMEIzRDVDIj5FeHRlcm5hbCAvIHVudHJ1c3RlZDwvdGV4dD4KICA8cmVjdCB4PSI2MTUiIHk9IjM2MCIgd2lkdGg9IjMzNSIgaGVpZ2h0PSI0MDUiIHJ4PSI4IiBmaWxsPSJub25lIiBzdHJva2U9IiM4RkE5QkMiIHN0cm9rZS13aWR0aD0iMS4yIiBzdHJva2UtZGFzaGFycmF5PSI2IDQiLz4KICA8dGV4dCB4PSI2MjkiIHk9IjM4MCIgZm9udC1zaXplPSIxMiIgZm9udC13ZWlnaHQ9ImJvbGQiIGZpbGw9IiMwQjNENUMiPkxvY2FsIGRhZW1vbiAobG9vcGJhY2spPC90ZXh0PgogIDxyZWN0IHg9IjEwMjAiIHk9IjE2MCIgd2lkdGg9IjM0MCIgaGVpZ2h0PSI0NTUiIHJ4PSI4IiBmaWxsPSJub25lIiBzdHJva2U9IiM4RkE5QkMiIHN0cm9rZS13aWR0aD0iMS4yIiBzdHJva2UtZGFzaGFycmF5PSI2IDQiLz4KICA8dGV4dCB4PSIxMDM0IiB5PSIxODAiIGZvbnQtc2l6ZT0iMTIiIGZvbnQtd2VpZ2h0PSJib2xkIiBmaWxsPSIjMEIzRDVDIj5BZ2VudCBob3N0PC90ZXh0PgogIDxyZWN0IHg9IjEzODUiIHk9IjE2MCIgd2lkdGg9IjI4MCIgaGVpZ2h0PSIzMjAiIHJ4PSI4IiBmaWxsPSJub25lIiBzdHJva2U9IiM4RkE5QkMiIHN0cm9rZS13aWR0aD0iMS4yIiBzdHJva2UtZGFzaGFycmF5PSI2IDQiLz4KICA8dGV4dCB4PSIxMzk5IiB5PSIxODAiIGZvbnQtc2l6ZT0iMTIiIGZvbnQtd2VpZ2h0PSJib2xkIiBmaWxsPSIjMEIzRDVDIj5Db25maWcgJmFtcDsgY29udHJvbHM8L3RleHQ+CgogIDwhLS0gdGl0bGUgLS0+CiAgPHRleHQgeD0iNDAiIHk9IjQyIiBmb250LXNpemU9IjIzIiBmb250LXdlaWdodD0iYm9sZCIgZmlsbD0iIzBCM0Q1QyI+SGVybWVzIEFnZW50IG9uIFNpZ25hbDogSGFyZGVuZWQgUmVmZXJlbmNlIEFyY2hpdGVjdHVyZTwvdGV4dD4KICA8dGV4dCB4PSI0MCIgeT0iNjgiIGZvbnQtc2l6ZT0iMTMiIGZpbGw9IiM2QjdDOEMiPkxvb3BiYWNrLWJvdW5kIGxpbmtlZC1kZXZpY2UgZ2F0ZXdheSB3aXRoIGEgcGVyLWNoYW5uZWwgbGVhc3QtcHJpdmlsZWdlIHRvb2xzZXQgwrcgVHlwZSAxIHZpZXc8L3RleHQ+CgogIDwhLS0gZWRnZXMgKGRyYXduIGJlZm9yZSBub2RlcyBzbyBub2RlcyBzaXQgb24gdG9wIG9mIGFueSBlbmRwb2ludCkgLS0+CiAgPCEtLSBFMSBwaG9uZTwtPnNlcnZlcnMgLS0+CiAgPHBvbHlsaW5lIHBvaW50cz0iMjUwLDQ2MCAzMDAsNDYwIiBmaWxsPSJub25lIiBzdHJva2U9IiMzNDQ5NUUiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWRhc2hhcnJheT0iNiA0IiBtYXJrZXItc3RhcnQ9InVybCgjYVNsYXRlKSIgbWFya2VyLWVuZD0idXJsKCNhU2xhdGUpIi8+CiAgPHJlY3QgeD0iMjMzIiB5PSI1MjciIHdpZHRoPSI4NCIgaGVpZ2h0PSIxNiIgZmlsbD0iI0ZGRkZGRiIvPgogIDx0ZXh0IHg9IjI3NSIgeT0iNTM5IiBmb250LXNpemU9IjEwLjUiIGZvbnQtd2VpZ2h0PSJib2xkIiBmaWxsPSIjMzQ0OTVFIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIj5jbG91ZCBjaGF0PC90ZXh0PgogIDwhLS0gRTIgc2VydmVycy0+ZGFlbW9uIC0tPgogIDxwb2x5bGluZSBwb2ludHM9IjUzMCw0NjAgNTkwLDQ2MCA1OTAsNDcwIDY1MCw0NzAiIGZpbGw9Im5vbmUiIHN0cm9rZT0iIzM0NDk1RSIgc3Ryb2tlLXdpZHRoPSIyLjIiIG1hcmtlci1lbmQ9InVybCgjYVNsYXRlKSIvPgogIDxyZWN0IHg9IjUzNiIgeT0iNDQwIiB3aWR0aD0iMTA4IiBoZWlnaHQ9IjE2IiBmaWxsPSIjRkZGRkZGIi8+CiAgPHRleHQgeD0iNTkwIiB5PSI0NTIiIGZvbnQtc2l6ZT0iMTAuNSIgZm9udC13ZWlnaHQ9ImJvbGQiIGZpbGw9IiMzNDQ5NUUiIHRleHQtYW5jaG9yPSJtaWRkbGUiPmxpbmtlZC1kZXZpY2Ugc3luYzwvdGV4dD4KICA8IS0tIEUzIGRhZW1vbjwtPmdhdGV3YXkgLS0+CiAgPHBvbHlsaW5lIHBvaW50cz0iOTMwLDQxNSA5OTAsNDE1IDk5MCwyNTUgMTA1MCwyNTUiIGZpbGw9Im5vbmUiIHN0cm9rZT0iIzFGN0E4QyIgc3Ryb2tlLXdpZHRoPSIyLjIiIG1hcmtlci1zdGFydD0idXJsKCNhVGVhbCkiIG1hcmtlci1lbmQ9InVybCgjYVRlYWwpIi8+CiAgPHJlY3QgeD0iOTk3IiB5PSIzMDAiIHdpZHRoPSIxNTAiIGhlaWdodD0iMzQiIGZpbGw9IiNGRkZGRkYiLz4KICA8dGV4dCB4PSIxMDAzIiB5PSIzMTQiIGZvbnQtc2l6ZT0iMTAuNSIgZm9udC13ZWlnaHQ9ImJvbGQiIGZpbGw9IiMxRjdBOEMiPmxvb3BiYWNrIEhUVFAgOjgwODA8L3RleHQ+CiAgPHRleHQgeD0iMTAwMyIgeT0iMzI4IiBmb250LXNpemU9IjEwLjUiIGZvbnQtd2VpZ2h0PSJib2xkIiBmaWxsPSIjMUY3QThDIj5pbmJvdW5kIC8gcmVwbHk8L3RleHQ+CiAgPCEtLSBFNCBnYXRld2F5LT50ZXJtaW5hbCAtLT4KICA8cG9seWxpbmUgcG9pbnRzPSIxMTk1LDMyMCAxMTk1LDM1MCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjMUY3QThDIiBzdHJva2Utd2lkdGg9IjIuMiIgbWFya2VyLWVuZD0idXJsKCNhVGVhbCkiLz4KICA8cmVjdCB4PSIxMjAxIiB5PSIzMjciIHdpZHRoPSI1MiIgaGVpZ2h0PSIxNiIgZmlsbD0iI0ZGRkZGRiIvPgogIDx0ZXh0IHg9IjEyMDUiIHk9IjMzOSIgZm9udC1zaXplPSIxMC41IiBmb250LXdlaWdodD0iYm9sZCIgZmlsbD0iIzFGN0E4QyI+dG9vbCBjYWxsPC90ZXh0PgogIDwhLS0gRTUgdGVybWluYWwtPnNlbmQgKGZpbmRpbmcpIC0tPgogIDxwb2x5bGluZSBwb2ludHM9IjExOTUsNDUwIDExOTUsNDkwIiBmaWxsPSJub25lIiBzdHJva2U9IiNDMDM5MkIiIHN0cm9rZS13aWR0aD0iMi4yIiBzdHJva2UtZGFzaGFycmF5PSI2IDQiIG1hcmtlci1lbmQ9InVybCgjYVJlZCkiLz4KICA8cmVjdCB4PSIxMjAxIiB5PSI0NjEiIHdpZHRoPSIxOTYiIGhlaWdodD0iMTYiIGZpbGw9IiNGRkZGRkYiLz4KICA8dGV4dCB4PSIxMjA1IiB5PSI0NzMiIGZvbnQtc2l6ZT0iMTAuNSIgZm9udC13ZWlnaHQ9ImJvbGQiIGZpbGw9IiNDMDM5MkIiPnNoZWxsIGV4ZWMg4oaSIGRlZmVhdHMgc2VuZCBndWFyZDwvdGV4dD4KICA8IS0tIEU2IHNlbmQtPmRhZW1vbiAob3V0Ym91bmQgbG9vcCkgLS0+CiAgPHBvbHlsaW5lIHBvaW50cz0iMTA1MCw1NDAgOTg1LDU0MCA5ODUsNTEwIDkzMCw1MTAiIGZpbGw9Im5vbmUiIHN0cm9rZT0iIzJFN0QzMiIgc3Ryb2tlLXdpZHRoPSIyLjIiIG1hcmtlci1lbmQ9InVybCgjYUdyZWVuKSIvPgogIDxyZWN0IHg9IjkwNSIgeT0iNTQ2IiB3aWR0aD0iMTUwIiBoZWlnaHQ9IjE2IiBmaWxsPSIjRkZGRkZGIi8+CiAgPHRleHQgeD0iOTgwIiB5PSI1NTgiIGZvbnQtc2l6ZT0iMTAuNSIgZm9udC13ZWlnaHQ9ImJvbGQiIGZpbGw9IiMyRTdEMzIiIHRleHQtYW5jaG9yPSJtaWRkbGUiPnF1ZXVlIG91dGJvdW5kIChsb29wYmFjayk8L3RleHQ+CiAgPCEtLSBFNyBkYWVtb24tPmpvdXJuYWwgLS0+CiAgPHBvbHlsaW5lIHBvaW50cz0iNzkwLDU2MCA3OTAsNjIwIiBmaWxsPSJub25lIiBzdHJva2U9IiNFNEExMUIiIHN0cm9rZS13aWR0aD0iMi4yIiBtYXJrZXItZW5kPSJ1cmwoI2FBbWJlcikiLz4KICA8cmVjdCB4PSI3OTYiIHk9IjU4MiIgd2lkdGg9IjE3MCIgaGVpZ2h0PSIxNiIgZmlsbD0iI0ZGRkZGRiIvPgogIDx0ZXh0IHg9IjgwMCIgeT0iNTk0IiBmb250LXNpemU9IjEwLjUiIGZvbnQtd2VpZ2h0PSJib2xkIiBmaWxsPSIjRTRBMTFCIj5tZXNzYWdlIGJvZGllcyDihpIgLS1zY3J1Yi1sb2c8L3RleHQ+CiAgPCEtLSBFOCBjb25maWctPmdhdGV3YXkgLS0+CiAgPHBvbHlsaW5lIHBvaW50cz0iMTQwMCwyNTAgMTM3MCwyNTAgMTM3MCwyNTUgMTM0MCwyNTUiIGZpbGw9Im5vbmUiIHN0cm9rZT0iIzFGN0E4QyIgc3Ryb2tlLXdpZHRoPSIyIiBzdHJva2UtZGFzaGFycmF5PSI4IDgiIG1hcmtlci1lbmQ9InVybCgjYVRlYWwpIi8+CiAgPHJlY3QgeD0iMTMwMCIgeT0iMjMwIiB3aWR0aD0iMTUwIiBoZWlnaHQ9IjE2IiBmaWxsPSIjRkZGRkZGIi8+CiAgPHRleHQgeD0iMTM3NSIgeT0iMjQyIiBmb250LXNpemU9IjEwLjUiIGZvbnQtd2VpZ2h0PSJib2xkIiBmaWxsPSIjMUY3QThDIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIj5jb25maWcgKyB0b29sc2V0ICg2MDApPC90ZXh0PgogIDwhLS0gRTkgZGVueS0+dGVybWluYWwgLS0+CiAgPHBvbHlsaW5lIHBvaW50cz0iMTQwMCw0MDUgMTM3MCw0MDUgMTM3MCw0MDAgMTM0MCw0MDAiIGZpbGw9Im5vbmUiIHN0cm9rZT0iIzZCN0M4QyIgc3Ryb2tlLXdpZHRoPSIyIiBzdHJva2UtZGFzaGFycmF5PSI4IDgiIG1hcmtlci1lbmQ9InVybCgjYUdyZXkpIi8+CiAgPHJlY3QgeD0iMTMwNSIgeT0iMzgxIiB3aWR0aD0iMTQwIiBoZWlnaHQ9IjE2IiBmaWxsPSIjRkZGRkZGIi8+CiAgPHRleHQgeD0iMTM3NSIgeT0iMzkzIiBmb250LXNpemU9IjEwLjUiIGZvbnQtd2VpZ2h0PSJib2xkIiBmaWxsPSIjNkI3QzhDIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIj5kZW55IGZsb29yIChwcmUtYnlwYXNzKTwvdGV4dD4KCiAgPCEtLSBub2RlcyAtLT4KICA8IS0tIFBob25lIC0tPgogIDxyZWN0IHg9IjQwIiB5PSI0MDAiIHdpZHRoPSIyMTAiIGhlaWdodD0iMTIwIiByeD0iOSIgZmlsbD0iI0VFRjFGNCIgc3Ryb2tlPSIjMzQ0OTVFIiBzdHJva2Utd2lkdGg9IjEuOCIvPgogIDx0ZXh0IHg9IjUyIiB5PSI0MjQiIGZvbnQtc2l6ZT0iMTIuNSIgZm9udC13ZWlnaHQ9ImJvbGQiIGZpbGw9IiMxQjJBMzMiPlBob25lIChwcmltYXJ5IGRldmljZSk8L3RleHQ+CiAgPHRleHQgeD0iNTIiIHk9IjQ0NCIgZm9udC1zaXplPSIxMS41IiBmaWxsPSIjMUIyQTMzIj5Ib2xkcyB0aGUgU2lnbmFsIGFjY291bnQuPC90ZXh0PgogIDx0ZXh0IHg9IjUyIiB5PSI0NjEiIGZvbnQtc2l6ZT0iMTEuNSIgZmlsbD0iIzFCMkEzMyI+U3RheXMgcHJpbWFyeTsgYXBwcm92ZXM8L3RleHQ+CiAgPHRleHQgeD0iNTIiIHk9IjQ3OCIgZm9udC1zaXplPSIxMS41IiBmaWxsPSIjMUIyQTMzIj50aGUgZGV2aWNlIGxpbmsuPC90ZXh0PgogIDwhLS0gU2VydmVycyAtLT4KICA8cmVjdCB4PSIzMDAiIHk9IjQwMCIgd2lkdGg9IjIzMCIgaGVpZ2h0PSIxMjAiIHJ4PSI5IiBmaWxsPSIjRUVGMUY0IiBzdHJva2U9IiMzNDQ5NUUiIHN0cm9rZS13aWR0aD0iMS44Ii8+CiAgPHRleHQgeD0iMzEyIiB5PSI0MjQiIGZvbnQtc2l6ZT0iMTIuNSIgZm9udC13ZWlnaHQ9ImJvbGQiIGZpbGw9IiMxQjJBMzMiPlNpZ25hbCBzZXJ2ZXJzPC90ZXh0PgogIDx0ZXh0IHg9IjMxMiIgeT0iNDQ0IiBmb250LXNpemU9IjExLjUiIGZpbGw9IiMxQjJBMzMiPkNsb3VkIHJlbGF5LiBFbmQtdG8tZW5kPC90ZXh0PgogIDx0ZXh0IHg9IjMxMiIgeT0iNDYxIiBmb250LXNpemU9IjExLjUiIGZpbGw9IiMxQjJBMzMiPmVuY3J5cHRlZCBiZXR3ZWVuIGRldmljZXM7PC90ZXh0PgogIDx0ZXh0IHg9IjMxMiIgeT0iNDc4IiBmb250LXNpemU9IjExLjUiIGZpbGw9IiMxQjJBMzMiPm5vdCBhIGhvc3QgdHJ1c3QgYW5jaG9yLjwvdGV4dD4KICA8IS0tIERhZW1vbiAtLT4KICA8cmVjdCB4PSI2NTAiIHk9IjM4MCIgd2lkdGg9IjI4MCIgaGVpZ2h0PSIxODAiIHJ4PSI5IiBmaWxsPSIjRTdGM0U4IiBzdHJva2U9IiMyRTdEMzIiIHN0cm9rZS13aWR0aD0iMS44Ii8+CiAgPHRleHQgeD0iNjYyIiB5PSI0MDYiIGZvbnQtc2l6ZT0iMTIuNSIgZm9udC13ZWlnaHQ9ImJvbGQiIGZpbGw9IiMxQjJBMzMiPnNpZ25hbC1jbGkgZGFlbW9uPC90ZXh0PgogIDx0ZXh0IHg9IjY2MiIgeT0iNDI4IiBmb250LXNpemU9IjExLjUiIGZpbGw9IiMxQjJBMzMiPkxpbmtlZCBzZWNvbmRhcnkgZGV2aWNlLjwvdGV4dD4KICA8dGV4dCB4PSI2NjIiIHk9IjQ0NiIgZm9udC1zaXplPSIxMS41IiBmaWxsPSIjMUIyQTMzIj5IVFRQIGJvdW5kIHRvPC90ZXh0PgogIDx0ZXh0IHg9IjY2MiIgeT0iNDYzIiBmb250LXNpemU9IjExLjUiIGZpbGw9IiMxQjJBMzMiPjEyNy4wLjAuMTo4MDgwIG9ubHkuPC90ZXh0PgogIDx0ZXh0IHg9IjY2MiIgeT0iNDgzIiBmb250LXNpemU9IjExLjUiIGZpbGw9IiMxQjJBMzMiPlNlbmRzIGFuZCByZWNlaXZlcyBhczwvdGV4dD4KICA8dGV4dCB4PSI2NjIiIHk9IjUwMCIgZm9udC1zaXplPSIxMS41IiBmaWxsPSIjMUIyQTMzIj50aGUgYWNjb3VudC48L3RleHQ+CiAgPCEtLSBHYXRld2F5IC0tPgogIDxyZWN0IHg9IjEwNTAiIHk9IjE5MCIgd2lkdGg9IjI5MCIgaGVpZ2h0PSIxMzAiIHJ4PSI5IiBmaWxsPSIjRTRGMUY0IiBzdHJva2U9IiMxRjdBOEMiIHN0cm9rZS13aWR0aD0iMS44Ii8+CiAgPHRleHQgeD0iMTA2MiIgeT0iMjE0IiBmb250LXNpemU9IjEyLjUiIGZvbnQtd2VpZ2h0PSJib2xkIiBmaWxsPSIjMUIyQTMzIj5BZ2VudCBnYXRld2F5IChTaWduYWwpPC90ZXh0PgogIDx0ZXh0IHg9IjEwNjIiIHk9IjIzNCIgZm9udC1zaXplPSIxMS41IiBmaWxsPSIjMUIyQTMzIj5OYXJyb3dlZCB0b29sc2V0OiBubyBicm93c2VyLDwvdGV4dD4KICA8dGV4dCB4PSIxMDYyIiB5PSIyNTEiIGZvbnQtc2l6ZT0iMTEuNSIgZmlsbD0iIzFCMkEzMyI+bm8gY29kZSBleGVjdXRpb24sIG5vPC90ZXh0PgogIDx0ZXh0IHg9IjEwNjIiIHk9IjI2OCIgZm9udC1zaXplPSIxMS41IiBmaWxsPSIjMUIyQTMzIj5zY2hlZHVsZXIsIG5vIGRlbGVnYXRpb24uPC90ZXh0PgogIDx0ZXh0IHg9IjEwNjIiIHk9IjI4OCIgZm9udC1zaXplPSIxMS41IiBmaWxsPSIjMUIyQTMzIj5EZW5pZXMgdW5rbm93biBzZW5kZXJzLjwvdGV4dD4KICA8IS0tIFRlcm1pbmFsIC0tPgogIDxyZWN0IHg9IjEwNTAiIHk9IjM1MCIgd2lkdGg9IjI5MCIgaGVpZ2h0PSIxMDAiIHJ4PSI5IiBmaWxsPSIjRkRGM0RGIiBzdHJva2U9IiNFNEExMUIiIHN0cm9rZS13aWR0aD0iMS44Ii8+CiAgPHRleHQgeD0iMTA2MiIgeT0iMzc0IiBmb250LXNpemU9IjEyLjUiIGZvbnQtd2VpZ2h0PSJib2xkIiBmaWxsPSIjMUIyQTMzIj50ZXJtaW5hbCB0b29sIChyZXRhaW5lZCk8L3RleHQ+CiAgPHRleHQgeD0iMTA2MiIgeT0iMzk0IiBmb250LXNpemU9IjExLjUiIGZpbGw9IiMxQjJBMzMiPlRoZSBvbmUgYnJvYWQgdG9vbCBrZXB0IG9uPC90ZXh0PgogIDx0ZXh0IHg9IjEwNjIiIHk9IjQxMSIgZm9udC1zaXplPSIxMS41IiBmaWxsPSIjMUIyQTMzIj50aGUgY2hhbm5lbC4gVGhlIGhvbmVzdCBjb3N0PC90ZXh0PgogIDx0ZXh0IHg9IjEwNjIiIHk9IjQyOCIgZm9udC1zaXplPSIxMS41IiBmaWxsPSIjMUIyQTMzIj5vZiBvdXRib3VuZCBzZW5kaW5nLjwvdGV4dD4KICA8IS0tIFNlbmQgLS0+CiAgPHJlY3QgeD0iMTA1MCIgeT0iNDkwIiB3aWR0aD0iMjkwIiBoZWlnaHQ9IjEwMCIgcng9IjkiIGZpbGw9IiNFN0YzRTgiIHN0cm9rZT0iIzJFN0QzMiIgc3Ryb2tlLXdpZHRoPSIxLjgiLz4KICA8dGV4dCB4PSIxMDYyIiB5PSI1MTQiIGZvbnQtc2l6ZT0iMTIuNSIgZm9udC13ZWlnaHQ9ImJvbGQiIGZpbGw9IiMxQjJBMzMiPmhlcm1lcyBzZW5kIChDTEkpPC90ZXh0PgogIDx0ZXh0IHg9IjEwNjIiIHk9IjUzNCIgZm9udC1zaXplPSIxMS41IiBmaWxsPSIjMUIyQTMzIj5TdXBwb3J0ZWQgb3V0Ym91bmQgcGF0aC48L3RleHQ+CiAgPHRleHQgeD0iMTA2MiIgeT0iNTUxIiBmb250LXNpemU9IjExLjUiIGZpbGw9IiMxQjJBMzMiPkFkZHJlc3NlcyBhbnkgY29udGFjdCBpbjwvdGV4dD4KICA8dGV4dCB4PSIxMDYyIiB5PSI1NjgiIGZvbnQtc2l6ZT0iMTEuNSIgZmlsbD0iIzFCMkEzMyI+RS4xNjQgZm9ybS48L3RleHQ+CgogIDwhLS0gSm91cm5hbCBjeWxpbmRlciAtLT4KICA8cGF0aCBkPSJNNjcwLDYzMiBMNjcwLDczOCBBMTIwLDEyIDAgMCAwIDkxMCw3MzggTDkxMCw2MzIiIGZpbGw9IiNGREYzREYiIHN0cm9rZT0iI0U0QTExQiIgc3Ryb2tlLXdpZHRoPSIxLjgiLz4KICA8ZWxsaXBzZSBjeD0iNzkwIiBjeT0iNjMyIiByeD0iMTIwIiByeT0iMTIiIGZpbGw9IiNGREYzREYiIHN0cm9rZT0iI0U0QTExQiIgc3Ryb2tlLXdpZHRoPSIxLjgiLz4KICA8dGV4dCB4PSI3OTAiIHk9IjY2MiIgZm9udC1zaXplPSIxMiIgZm9udC13ZWlnaHQ9ImJvbGQiIGZpbGw9IiMxQjJBMzMiIHRleHQtYW5jaG9yPSJtaWRkbGUiPlN5c3RlbSBqb3VybmFsPC90ZXh0PgogIDx0ZXh0IHg9Ijc5MCIgeT0iNjgyIiBmb250LXNpemU9IjExIiBmaWxsPSIjMUIyQTMzIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIj5Cb2RpZXMgbG9nZ2VkIGluIGNsZWFyIHRleHQuPC90ZXh0PgogIDx0ZXh0IHg9Ijc5MCIgeT0iNjk5IiBmb250LXNpemU9IjExIiBmaWxsPSIjMUIyQTMzIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIj5GaXg6IC0tc2NydWItbG9nLjwvdGV4dD4KCiAgPCEtLSBDb25maWcgY3lsaW5kZXIgLS0+CiAgPHBhdGggZD0iTTE0MDAsMjAyIEwxNDAwLDI5OCBBMTI1LDEyIDAgMCAwIDE2NTAsMjk4IEwxNjUwLDIwMiIgZmlsbD0iI0U0RjFGNCIgc3Ryb2tlPSIjMUY3QThDIiBzdHJva2Utd2lkdGg9IjEuOCIvPgogIDxlbGxpcHNlIGN4PSIxNTI1IiBjeT0iMjAyIiByeD0iMTI1IiByeT0iMTIiIGZpbGw9IiNFNEYxRjQiIHN0cm9rZT0iIzFGN0E4QyIgc3Ryb2tlLXdpZHRoPSIxLjgiLz4KICA8dGV4dCB4PSIxNTI1IiB5PSIyMzIiIGZvbnQtc2l6ZT0iMTIiIGZvbnQtd2VpZ2h0PSJib2xkIiBmaWxsPSIjMUIyQTMzIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIj5jb25maWcueWFtbCArIC5lbnY8L3RleHQ+CiAgPHRleHQgeD0iMTUyNSIgeT0iMjUyIiBmb250LXNpemU9IjExIiBmaWxsPSIjMUIyQTMzIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIj5Ub29sc2V0IGFuZCBjcmVkZW50aWFscy48L3RleHQ+CiAgPHRleHQgeD0iMTUyNSIgeT0iMjY5IiBmb250LXNpemU9IjExIiBmaWxsPSIjMUIyQTMzIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIj5Nb2RlIDYwMC48L3RleHQ+CgogIDwhLS0gRGVueSAtLT4KICA8cmVjdCB4PSIxNDAwIiB5PSIzNTAiIHdpZHRoPSIyNTAiIGhlaWdodD0iMTEwIiByeD0iOSIgZmlsbD0iI0U0RjFGNCIgc3Ryb2tlPSIjMUY3QThDIiBzdHJva2Utd2lkdGg9IjEuOCIvPgogIDx0ZXh0IHg9IjE0MTIiIHk9IjM3NCIgZm9udC1zaXplPSIxMi41IiBmb250LXdlaWdodD0iYm9sZCIgZmlsbD0iIzFCMkEzMyI+YXBwcm92YWxzLmRlbnkgZmxvb3I8L3RleHQ+CiAgPHRleHQgeD0iMTQxMiIgeT0iMzk0IiBmb250LXNpemU9IjExLjUiIGZpbGw9IiMxQjJBMzMiPlBhdHRlcm4gYmxvY2sgZXZhbHVhdGVkPC90ZXh0PgogIDx0ZXh0IHg9IjE0MTIiIHk9IjQxMSIgZm9udC1zaXplPSIxMS41IiBmaWxsPSIjMUIyQTMzIj5iZWZvcmUgYW55IGJ5cGFzcy48L3RleHQ+CgogIDwhLS0gTGVnZW5kIC0tPgogIDxyZWN0IHg9IjEzODUiIHk9IjUwMCIgd2lkdGg9IjI4MCIgaGVpZ2h0PSIyNTgiIHJ4PSI5IiBmaWxsPSIjRkJGREZFIiBzdHJva2U9IiM2QjdDOEMiIHN0cm9rZS13aWR0aD0iMS4zIiBzdHJva2UtZGFzaGFycmF5PSI2IDQiLz4KICA8dGV4dCB4PSIxNDAxIiB5PSI1MjQiIGZvbnQtc2l6ZT0iMTIuNSIgZm9udC13ZWlnaHQ9ImJvbGQiIGZpbGw9IiMwQjNENUMiPkNsYXNzaWZpY2F0aW9uPC90ZXh0PgogIDxyZWN0IHg9IjE0MDEiIHk9IjU0MCIgd2lkdGg9IjE2IiBoZWlnaHQ9IjEyIiBmaWxsPSIjRTdGM0U4IiBzdHJva2U9IiMyRTdEMzIiIHN0cm9rZS13aWR0aD0iMS42Ii8+CiAgPHRleHQgeD0iMTQyNSIgeT0iNTUwIiBmb250LXNpemU9IjExIiBmaWxsPSIjMzQ0OTVFIj5UcnVzdGVkIGxvY2FsIHNlcnZpY2U8L3RleHQ+CiAgPHJlY3QgeD0iMTQwMSIgeT0iNTY2IiB3aWR0aD0iMTYiIGhlaWdodD0iMTIiIGZpbGw9IiNFNEYxRjQiIHN0cm9rZT0iIzFGN0E4QyIgc3Ryb2tlLXdpZHRoPSIxLjYiLz4KICA8dGV4dCB4PSIxNDI1IiB5PSI1NzYiIGZvbnQtc2l6ZT0iMTEiIGZpbGw9IiMzNDQ5NUUiPkFnZW50IGdhdGV3YXkgJmFtcDsgY29udHJvbHM8L3RleHQ+CiAgPHJlY3QgeD0iMTQwMSIgeT0iNTkyIiB3aWR0aD0iMTYiIGhlaWdodD0iMTIiIGZpbGw9IiNGREYzREYiIHN0cm9rZT0iI0U0QTExQiIgc3Ryb2tlLXdpZHRoPSIxLjYiLz4KICA8dGV4dCB4PSIxNDI1IiB5PSI2MDIiIGZvbnQtc2l6ZT0iMTEiIGZpbGw9IiMzNDQ5NUUiPkF0dGVudGlvbiAvIHJlc2lkdWFsIHJpc2s8L3RleHQ+CiAgPHJlY3QgeD0iMTQwMSIgeT0iNjE4IiB3aWR0aD0iMTYiIGhlaWdodD0iMTIiIGZpbGw9IiNFRUYxRjQiIHN0cm9rZT0iIzM0NDk1RSIgc3Ryb2tlLXdpZHRoPSIxLjYiLz4KICA8dGV4dCB4PSIxNDI1IiB5PSI2MjgiIGZvbnQtc2l6ZT0iMTEiIGZpbGw9IiMzNDQ5NUUiPkV4dGVybmFsIC8gdW50cnVzdGVkPC90ZXh0PgogIDxsaW5lIHgxPSIxNDAxIiB5MT0iNjUwIiB4Mj0iMTQxNyIgeTI9IjY1MCIgc3Ryb2tlPSIjQzAzOTJCIiBzdHJva2Utd2lkdGg9IjIuNCIgc3Ryb2tlLWRhc2hhcnJheT0iNSAzIi8+CiAgPHRleHQgeD0iMTQyNSIgeT0iNjU0IiBmb250LXNpemU9IjExIiBmaWxsPSIjMzQ0OTVFIj5TZWN1cml0eSBmaW5kaW5nIHBhdGg8L3RleHQ+CiAgPGxpbmUgeDE9IjE0MDEiIHkxPSI2NzYiIHgyPSIxNDE3IiB5Mj0iNjc2IiBzdHJva2U9IiM2QjdDOEMiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWRhc2hhcnJheT0iNiA1Ii8+CiAgPHRleHQgeD0iMTQyNSIgeT0iNjgwIiBmb250LXNpemU9IjExIiBmaWxsPSIjMzQ0OTVFIj5Db250cm9sIC8gY29uZmlnIGxpbms8L3RleHQ+CiAgPHRleHQgeD0iMTQwMSIgeT0iNzA2IiBmb250LXNpemU9IjEwLjUiIGZpbGw9IiM2QjdDOEMiPlNvbGlkIGFycm93ID0gZGF0YSAvIG1lc3NhZ2UgZmxvdy48L3RleHQ+CiAgPHRleHQgeD0iMTQwMSIgeT0iNzIyIiBmb250LXNpemU9IjEwLjUiIGZpbGw9IiM2QjdDOEMiPkRvdWJsZSBhcnJvdyA9IGJpZGlyZWN0aW9uYWwuPC90ZXh0PgogIDx0ZXh0IHg9IjE0MDEiIHk9IjczOCIgZm9udC1zaXplPSIxMC41IiBmaWxsPSIjNkI3QzhDIj5SZWFkcyBpbiBncmV5c2NhbGUgYnkgcG9zaXRpb24uPC90ZXh0PgoKICA8IS0tIE5hcnJhdGl2ZSBub3RlIC0tPgogIDxyZWN0IHg9IjQwIiB5PSI3OTUiIHdpZHRoPSIxMzEwIiBoZWlnaHQ9IjE1MCIgcng9IjciIGZpbGw9IiNGRkY3RTYiIHN0cm9rZT0iI0U0QTExQiIgc3Ryb2tlLXdpZHRoPSIxLjQiLz4KICA8dGV4dCB4PSI1NiIgeT0iODIwIiBmb250LXNpemU9IjEyLjUiIGZvbnQtd2VpZ2h0PSJib2xkIiBmaWxsPSIjMEIzRDVDIj5XaHkgdGhpcyBzaGFwZTwvdGV4dD4KICA8dGV4dCB4PSI1NiIgeT0iODQyIiBmb250LXNpemU9IjExLjUiIGZpbGw9IiMzNDQ5NUUiPlRoZSB3b3Jrc3RhdGlvbiBhdHRhY2hlcyB0byBTaWduYWwgYXMgYSBsaW5rZWQgc2Vjb25kYXJ5IGRldmljZSwgc28gdGhlIGRhZW1vbiBiaW5kcyB0byBsb29wYmFjayBhbG9uZSBhbmQgdGhlIHBob25lIHN0YXlzIHByaW1hcnkuPC90ZXh0PgogIDx0ZXh0IHg9IjU2IiB5PSI4NjEiIGZvbnQtc2l6ZT0iMTEuNSIgZmlsbD0iIzM0NDk1RSI+VGhlIFNpZ25hbCBjaGFubmVsIHJ1bnMgYSBkZWxpYmVyYXRlbHkgbmFycm93ZWQgdG9vbHNldC4gUmV0YWluaW5nIHRoZSB0ZXJtaW5hbCwgaG93ZXZlciwgbGV0cyB0aGUgYWdlbnQgcmVhY2ggdGhlIGhlcm1lcyBzZW5kIENMSSBhbmQ8L3RleHQ+CiAgPHRleHQgeD0iNTYiIHk9Ijg4MCIgZm9udC1zaXplPSIxMS41IiBmaWxsPSIjMzQ0OTVFIj5tZXNzYWdlIGFueSBjb250YWN0LCB3aGljaCByZXN0b3JlcyB0aGUgdmVyeSBjYXBhYmlsaXR5IHRoZSBmcmFtZXdvcmsgd2l0aGhvbGRzIGZyb20gdGhlIGFnZW50IGxvb3A7IHRoZSB0cmFkZSBpcyBtYWRlIGtub3dpbmdseS48L3RleHQ+CiAgPHRleHQgeD0iNTYiIHk9Ijg5OSIgZm9udC1zaXplPSIxMS41IiBmaWxsPSIjMzQ0OTVFIj5UaGUgZGFlbW9uIHdyaXRlcyBtZXNzYWdlIGJvZGllcyB0byB0aGUgc3lzdGVtIGpvdXJuYWwgaW4gY2xlYXIgdGV4dCwgbWl0aWdhdGVkIHdpdGggLS1zY3J1Yi1sb2cuIEFjY2VzcyBjb250cm9sIChhbiBhbGxvdy1saXN0IG9mIG9uZTwvdGV4dD4KICA8dGV4dCB4PSI1NiIgeT0iOTE4IiBmb250LXNpemU9IjExLjUiIGZpbGw9IiMzNDQ5NUUiPm51bWJlciwgZ3JvdXBzIGlnbm9yZWQpIGlzIHRoZSBzaW5nbGUgY29udHJvbCBiZXR3ZWVuIGFuIGluYm91bmQgbWVzc2FnZSBhbmQgYSBzaGVsbCwgc28gaXQgaXMgbG9hZC1iZWFyaW5nIHJhdGhlciB0aGFuIG9wdGlvbmFsLjwvdGV4dD4KCiAgPCEtLSB2ZXJzaW9uIGxpbmUgLS0+CiAgPHRleHQgeD0iNDAiIHk9Ijk3MiIgZm9udC1zaXplPSIxMSIgZmlsbD0iIzZCN0M4QyI+UmVmZXJlbmNlIGFyY2hpdGVjdHVyZSDCtyBUeXBlIDEgdmlldyDCtyBBdXRob3I6IE5ldW1hbm5UZWNoVGlwcyDCtyB2MS4wIMK3IEF1Z3VzdCAyMDI2IMK3IEFsbCBpZGVudGlmaWVycyBpbGx1c3RyYXRpdmU8L3RleHQ+Cjwvc3ZnPgo=" width="100%">
</p>

> Reference architecture, Type 1 view. Stroke colour classifies each component, and the classification is spelled out in the legend, so the diagram still reads in greyscale. All identifiers shown are illustrative.

> 💡 **Tooltip (plain English):** think of `signal-cli` as a second device on your Signal account, like a linked desktop app, but headless. The agent talks to it only over a private internal channel that never leaves the machine.

Three properties of the linked-device model drive the decisions that follow:

- A Java runtime is mandatory, because `signal-cli` is a JVM application.
- The daemon is a long-lived service with a lifecycle independent of the agent gateway, so it belongs under a supervised `systemd` user unit.
- Because the workstation binds to your own identity rather than a segregated bot principal, it inherits full read and send authority over your account. That is precisely the capability you want and precisely the blast radius you must contain, which is why the inbound access control is load-bearing rather than cosmetic.

---

## 🎯 Threat model in brief

A compact model, mapped to recognised categories so it travels:

| Ref | Threat | Vector | Control |
|---|---|---|---|
| T1 | Inbound RCE | Untrusted message reaches a shell-capable agent | Deny-by-default allow-list; least-privilege toolset |
| T2 | Prompt injection | Adversarial text or fetched content steers the agent | Remove browser and web-fetch tools from the adapter |
| T3 | Credential exfiltration | Agent reads `.env` and sends the token out its own channel | `approvals.deny` glob on secret paths; file mode 600 |
| T4 | Data egress | Message bodies and attachments carry content off-host | Tool-layer restriction; the transport itself is unbounded |
| T5 | Data-at-rest disclosure | Daemon logs clear-text bodies to the journal | `--scrub-log`; journald retention limits |

> 💡 **Tooltip (plain English):** <abbr title="Remote Code Execution: an attacker getting your machine to run their commands from afar">RCE</abbr> is the worst case, someone running commands on your box remotely. <abbr title="Prompt injection: hiding instructions inside content the AI reads, so it obeys the attacker instead of you">Prompt injection</abbr> is subtler, hiding instructions inside a message so the agent follows them. The controls on the right are how each is blunted.

---

## 🧰 Before you start

| Requirement | Rationale |
|---|---|
| A current `signal-cli` release | Provides the linked-device transport and the JSON-RPC surface |
| A modern JDK | Recent `signal-cli` pins an up-to-date Java; an older JVM fails at start-up rather than degrading |
| Your phone with Signal installed | Device linking is confirmed by scanning a QR code on the primary |
| Shell access to the host | Every step here is a local, auditable command |
| A verified config backup | Establishes a known-good rollback point before any mutation |

> ⚠️ **Verify the Java version against the `signal-cli` release notes, not an older blog.** The pin advances with releases; a JVM one major version behind throws a start-up exception that reads like a network fault and wastes an evening.

---

## 🔗 Part 1: Stand up the Signal link

### 1. Provision the runtime and client

Install a current headless JDK and a terminal QR encoder, pull the `signal-cli` release, verify its published checksum, and unpack it to a system path with a stable symlink.

### 2. Link the device

Linking enrols the workstation as a secondary device. It is externally visible, it appears under **Linked Devices** on the primary, and it is revocable only from the phone. Treat it as a deliberate, gated action.

```bash
signal-cli link -n "AgentHost-Workstation"
# Render the printed tsdevice: URI as a QR code, then scan from
# Signal > Settings > Linked Devices > Link New Device
```

> ⚠️ **Link, never register.** `link` enrols a secondary device under your existing identity. `register` claims a number as a fresh primary and will deregister your handset. Only `link` is correct here.

> 💡 **Tooltip (plain English):** linking is like pairing Signal Desktop. Registering is like moving your number to a new phone, which kicks the old one off. You want the first, never the second.

Pull initial state and confirm enrolment:

```bash
signal-cli listAccounts
```

### 3. Supervise the daemon as a user unit

Author the unit yourself and bind the HTTP surface to loopback explicitly. `--scrub-log` is set here as a default, closing finding T5 before the daemon ever writes.

```ini
[Unit]
Description=signal-cli daemon for the agent host
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Environment=SIGNAL_CLI_ACCOUNT=+15550000000
ExecStart=/usr/local/bin/signal-cli -a ${SIGNAL_CLI_ACCOUNT} daemon --http 127.0.0.1:8080 --scrub-log
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=default.target
```

Enable it, then assert the bind address. This check is not optional.

```bash
systemctl --user enable --now signal-cli.service
ss -ltnp | grep 8080     # expect 127.0.0.1:8080, never 0.0.0.0:8080
```

> ⚠️ **An unauthenticated JSON-RPC endpoint that can send as you must never bind to a routable interface.** A `0.0.0.0` bind is a critical misconfiguration: stop the service and correct the `--http` argument before proceeding.

> 💡 **Tooltip (plain English):** `127.0.0.1` means "this machine only". If you ever see `0.0.0.0`, the service is listening to the whole network, which would let others on your Wi-Fi send messages as you. Fix it immediately.

### 4. Bind the adapter and scope access

Set the adapter keys, then constrain the allow-list to your own principal and leave group access unset. Deny-by-default is the correct failure mode; preserve it.

```bash
SIGNAL_HTTP_URL=http://127.0.0.1:8080
SIGNAL_ACCOUNT=+15550000000
SIGNAL_ALLOWED_USERS=+15550000000
# Group access deliberately omitted (groups ignored).
# GATEWAY_ALLOW_ALL_USERS must never be set on this host.
```

```bash
chmod 600 ~/.hermes/.env
```

Unknown senders are refused until you issue a pairing approval, which keeps the trust boundary an explicit, human-gated act.

---

## ✉️ Part 2: Authenticated outbound messaging

A design point worth internalising before you reach for custom code: **outbound messaging ships with Hermes and sits deliberately outside the agent loop.** The model is not granted an agent-callable `send_message` tool; delivery is handled by first-party paths (`hermes send`, cron delivery, the gateway notifier). The supported command is a one-liner.

```bash
hermes send --to signal:+<E164 number> "message body"
```

Worked example with an illustrative number:

```bash
hermes send --to signal:+15551234567 "Dispatch from the agent host"
```

### Addressing contract

- The target is strict E.164: leading `+`, country code, digits, no separators. `+15551234567`, never `+1 555 123 4567`. A stray space forces channel-name resolution and the send fails.
- The body is a single double-quoted argument.
- A bare platform token routes to the configured home channel; an E.164 target routes to that recipient, resolved through the adapter's `listContacts` cache.

> 💡 **Tooltip (plain English):** the phone number must be written in the international format with a plus sign and no spaces, exactly like `+15551234567`. Get that right and the message just sends.

### Driving it through the agent

Because the Signal adapter retains the `terminal` tool, an instruction from your phone is executed by the agent shelling out to the same command. Constrain the instruction so a small model cannot improvise:

```
Run this exact command once, then report the command output verbatim and nothing else.

hermes send --to signal:+15551234567 "Message body here"
```

> ✅ **Supply the real number yourself and confirm delivery on the primary.** A `sent` result with exit code 0 means the CLI accepted the payload; ground truth is the message landing in the recipient thread on your handset, delivered as a sync copy from the linked device.

> 🚫 **Never leave a placeholder in the recipient field.** A malformed placeholder fails closed and is rejected. A well-formed but fabricated number does not fail closed, and would deliver to an unintended party.

---

## 🛡️ Part 3: Harden the channel

Here the default posture needs correcting. By default the Signal adapter resolves to `hermes-signal`, which is defined as `_HERMES_CORE_TOOLS`, the platform's **full-access** profile. That set includes `terminal`, `code_execution`, browser automation with Chrome DevTools Protocol access, a scheduler (`cronjob`), and task delegation, all reachable by any principal that can deliver an inbound message.

An inbound message is untrusted input. Granting it the full core toolset is functionally equivalent to exposing a shell behind a public form.

### Pin an explicit least-privilege toolset

Toolsets are configured per platform under `platform_toolsets`. Replace the inherited full-access profile on the Signal adapter with an explicit, narrower list.

```yaml
platform_toolsets:
  signal:
    - terminal
    - file
    - web
    - vision
    - skills
    - todo
    - memory
    - session_search
```

What this strips from the inbound surface, and the rationale:

| Removed | Rationale |
|---|---|
| `browser` (incl. CDP) | Eliminates the path by which untrusted fetched content reaches an unsandboxed agent (T2) |
| `code_execution` | No arbitrary code paths beyond the deliberately retained shell |
| `cronjob` | An inbound message cannot install standing, unattended egress (T4) |
| `delegation` | A single message cannot fan out into further agent runs |

`terminal` is retained by design. It is the mechanism that keeps `hermes send` reachable, and it is the honest cost of the capability: retaining it enables outbound messaging and simultaneously provides the agent a route to that command. You cannot satisfy the requirement without it in this design, so the trade is made explicitly rather than by omission.

> ℹ️ The resolver drops unknown or platform-restricted toolset names rather than trusting them, so a typo fails closed. Restart the gateway to load the change.

> 💡 **Tooltip (plain English):** you are handing the messaging channel a short, safe list of abilities instead of the full set. The one powerful ability you keep, the terminal, is the one that makes sending work, so you keep it on purpose and know the risk.

### Keep a deny floor beneath the toolset

Independently of the toolset, a pattern deny-list blocks dangerous invocations before any approval bypass is evaluated. A defensible baseline covers privilege escalation, shell piping, key material, firewall mutation, and destructive disk operations.

```yaml
approvals:
  mode: manual
  cron_mode: deny
  deny:
    - '*sudo *'
    - '*| bash*'
    - '*| sh*'
    - '*~/.ssh/*'
    - '*chmod*777*'
    - '*iptables*'
    - '*shred *'
    - '*wipefs*'
```

---

## 🔍 Verification

Do not trust the agent's self-description of its own privileges. Interrogate the framework's resolver directly, using the same function the gateway calls at dispatch.

```python
import yaml
from hermes_cli.tools_config import _get_platform_tools
cfg = yaml.safe_load(open("config.yaml"))
print("signal:", sorted(_get_platform_tools(cfg, "signal")))
print("cli:   ", sorted(_get_platform_tools(cfg, "cli")))
```

A correctly hardened Signal adapter shows `terminal` present and both the browser set and `code_execution` **absent**, while the CLI profile still lists them. If the two lines match, the restriction has not taken effect and the gateway needs a restart.

> 💡 **Tooltip (plain English):** rather than asking the agent "what can you do", you ask the program itself. That answer cannot be talked around. It is the difference between a claim and a fact.

Then run the two end-to-end checks that no log can fabricate:

1. Ask the agent over Signal to enumerate its tools, and diff against the resolver output.
2. Send to a consenting contact and confirm arrival in their thread on your handset.

---

## 🚨 Security findings

Three findings are worth publishing, because each is a general pattern rather than a local quirk.

### 🔴 A vendor safety control neutralised by local configuration

Hermes deliberately withholds an agent-callable `send_message` tool; outbound delivery is kept outside the agent loop so the model cannot autonomously message anyone. It is a sound piece of design.

Retaining `terminal` on the messaging adapter neutralises it. The agent can shell out to `hermes send` and reach any recipient. The control is not bypassed by a defect; it is cancelled by a configuration choice. If you narrow the toolset yet keep the shell, you have made this trade, and you should make it consciously.

### 🟠 Clear-text message bodies persisted to `journald`

Run as a service at default verbosity, the daemon echoes received envelopes, including sender identifiers and body text, to the systemd journal. The journal enforces no disappearing-message timer, so content you set to auto-delete in Signal persists at rest in a store that ignores that setting, readable by any principal with journal access and without touching the encrypted database.

Remediate with `--scrub-log` on the unit (shown in Part 1). Verify residue afterwards, since scrubbing is documented against identifiers rather than bodies, and fall back to journald retention limits if bodies persist.

### 🟡 The narrow surface hardened, the wide one left default

It is tempting to lock down the local CLI, where untrusted content rarely arrives, and leave the messaging adapter on the full-access default, where untrusted content arrives by design. The correct priority is inverted: harden the externally reachable channel first.

> These map cleanly onto recognised agentic-security guidance around **tool misuse**, **excessive agency**, and **insecure defaults**. Treat any inbound messaging adapter as an untrusted input surface and grant it the minimum privilege that still discharges the task.

> 💡 **Tooltip (plain English):** the headline lesson is that the "safe by default" assumption was wrong here. The convenient setting was also the dangerous one, and you have to change it on purpose.

---

## 🛠️ Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| `Could not resolve '+...'` | Malformed recipient, usually a stray space or leftover placeholder | Re-enter in strict E.164 |
| Daemon reachable by `curl`, gateway reports unreachable | SSRF URL validation on the adapter path | Apply a narrowly scoped allowance, not a blanket change |
| `config file is in use by another instance` | A second process is contending for the account lock | Confirm only the supervised daemon is running |
| Agent claims a tool it should not have | Session is reporting a cached schema, not its live resolution | Trust the resolver output over the self-report |
| Sent but not seen | Delivery latency, and self-sends surface under Note to Self | Check the recipient thread on the handset |

---

## 🎓 Lessons learned

- **Interrogate source, not summaries.** At several points the config file, the agent's self-report, and the resolver disagreed. Only the resolver, the framework's own code path, was authoritative. When an agent reports success, verify the artefact rather than the narrative.
- **Atomic instructions beat open goals with a small model.** A single fully specified command executed correctly; a broad objective was improvised and misreported. Specify the command, constrain the output, confirm the result.
- **A capable-looking build can be documentation drift.** Config described a plan already largely executed, in a different order than recorded. Reconcile the record against the running system before trusting either.
- **The guard rail and the feature are often one lever.** Retaining the shell both enables sending and defeats the vendor control. Name that trade openly rather than discovering it in an incident review.

---

## 📚 Reference

- Nous Research Hermes Agent, messaging gateway and Signal adapter documentation
- `signal-cli`, installation, device linking, and the JSON-RPC interface
- OWASP Top 10 for Agentic Applications, tool misuse and excessive agency
- NIST AI Risk Management Framework
- ISO/IEC 42001, AI management systems
- GDPR Article 25, data protection by design and by default

> All identifiers, phone numbers, account references, and hostnames in this document are illustrative. Replace them with your own before use.

---

## 🏷️ Topics

`#Signal` `#signal-cli` `#CyberSecurity` `#InfoSec` `#AIAgents` `#HermesAgent` `#NousResearch` `#LeastPrivilege` `#ZeroTrust` `#PromptInjection` `#OWASPTop10` `#AgenticAI` `#SelfHosted` `#DevSecOps` `#PrivacyByDesign` `#ThreatModelling` `#journald` `#Fedora` `#SystemHardening` `#E2EE`

---

## 📄 Licence

Released under the MIT Licence. See `LICENSE` for details.

---

<div align="center">

**Built and documented by [NeumannTechTips](https://github.com/NeumannTechTips)**

If this saved you an evening, a ⭐ is appreciated.

</div>
