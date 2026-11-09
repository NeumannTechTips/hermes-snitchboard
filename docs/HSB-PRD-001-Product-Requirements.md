# Hermes Snitchboard: product requirements

| Field | Detail |
|---|---|
| Document ID | HSB-PRD-001 |
| Version | 1.2, approved |
| Date | 9 November 2026 |
| Owner | NeumannTechTips |
| Repository | `NeumannTechTips/hermes-snitchboard` (private until the gate in section 11.3 passes) |
| Plugin name | `hermes-snitchboard`, display title "Hermes Snitchboard" |
| Target | Hermes Agent v0.23.0 or later, Linux |
| Status | **Approved for build on 9 November 2026.** Scope decision: full-fidelity port, built in priority tiers |

---

## 1. Problem

Hermes Agent runs shell commands, calls tools and reaches the network on its owner's behalf. The agent can report what it did, and application-layer tooling can record which model requests it issued. Neither answers the question a careful owner actually asks: what did this machine really connect to, and can the record of it be trusted?

An operating-system firewall such as OpenSnitch already observes every outbound connection together with the process responsible. That evidence is rich, yet it sits in a database few people open, and nothing in it distinguishes routine traffic from a destination seen for the first time, a heartbeat, or a connection made by AI tooling. Records held as ordinary rows can also be altered afterwards without anyone noticing.

Hermes Snitchboard closes that gap. It presents OpenSnitch connection evidence as a tab inside the Hermes dashboard: plain-language findings mapped to MITRE ATT&CK, with a hash chain that makes alteration of the stored history detectable.

## 2. Success criteria

| ID | Criterion | Measurement |
|---|---|---|
| SC1 | A reviewer without OpenSnitch sees a complete, working dashboard within two minutes of installing | Demonstration mode renders every shipped panel from bundled synthetic data, clearly badged |
| SC2 | `hermes plugins validate . --install-deps` and `hermes plugins doctor . --ci` pass at the pinned commit | Both run in continuous integration and locally |
| SC3 | No third-party runtime dependency | `plugin.yaml` declares none, and the engine imports only the standard library |
| SC4 | No personal or traceable data in the repository, its history, its screenshots or the video | History-wide scan, fixture range test and manual review all pass before publication |
| SC5 | The engine reproduces the rules in section 7.4 exactly | Unit tests with fixed fixtures for every rule, including boundary values |
| SC6 | Alteration of any full record, or of the order of the chain, is detected | A test edits one record and one chain link, then confirms verification fails and names the first broken run. A trimmed record's summary is not chain-covered, is labelled as such in the interface, and is excluded from this criterion by design (see 7.3) |
| SC7 | Every run record validates against the schema in section 7.3 | A schema validator runs over all fixtures and over collector output |
| SC8 | The submission is complete with a clear margin | Pull request opened, video posted and form submitted at least four hours before the cut-off |

## 3. Scope

### 3.1 In scope

A dashboard tab reproducing the full detail of the owner's existing OpenSnitch monitoring page, rebuilt against the Hermes plugin surfaces:

- A read-only backend serving run records from a configured directory.
- A deterministic analysis engine in Python, standard library only.
- Seventeen interface elements across three priority tiers, listed in section 7.9.
- A reference collector, run by the owner rather than by Hermes, building run records from the OpenSnitch statistics database.
- Demonstration mode backed by synthetic data from a committed generator.
- Redaction of addresses and names by default.
- Documentation: README, this document, a schema reference and a security note.

### 3.2 Out of scope

- Any action on the host. The plugin neither blocks, allows nor alters anything. It observes and reports.
- Any model call, outbound network call or telemetry.
- Decrypting or describing traffic content. A connection is reported as an event with byte counts where measured, never as content.
- Agent tools, hooks or middleware. Version 1 registers no capabilities.
- A Desktop pane, and any platform other than Linux.
- Correlating connections with individual Hermes tool calls, which is a candidate for a later version.
- Anchoring the hash chain outside the machine, such as a signed timestamp.

## 4. Users

| User | Need | Served by |
|---|---|---|
| Single-user Linux owner running Hermes and OpenSnitch | See what the machine reached, and notice anything new | Collector writes records, the tab reads them |
| Operator running Hermes under a separate service account | Review the evidence without granting the agent access to the raw firewall database | The collector runs under the owner's account; the plugin reads only a directory of records |
| Security or assurance reviewer | Evidence that a record has not been edited, and a defensible mapping to ATT&CK | Chain verification and the technique table |
| Hackathon reviewer | Judge the work quickly, without special setup | Demonstration mode |

## 5. Findings from the reference implementation

The owner's existing page was examined on 9 November 2026. Two findings shape the design and are recorded because they are easy to miss.

**5.1 The stored records are not schema-consistent.** Of twenty-eight runs, only two carry the detailed fields `agents`, `aggregates`, `beacons`, `novel`, `rows` and `volume`. Twenty-six are marked `trimmed`. Of ninety-two detections, only seven carry the full set of `attack`, `confidence`, `detail`, `evidence` and `recommendation`; the remainder hold `severity` and `title` alone. A distributable plugin cannot render reliably against records of varying shape, so section 7.3 defines a strict schema with a declared full form and a declared trimmed form, and section 9 requires a validator.

**5.2 Trimming breaks novelty unless a digest is retained.** Novelty is computed by counting how many prior runs contained each destination. A trimmed record that discards its destinations makes that count impossible. Trimmed records must therefore retain a compact destination set, as specified in section 7.3.

Two further points are favourable. The existing charts are already inline SVG driven by CSS variables rather than a charting library, so they transfer directly, which matters because the Hermes dashboard SDK ships no chart component. The only external dependency is a web font, and the only runtime coupling is a single browser API used for storage and downloads.

## 6. Requirements

### 6.1 Functional

| ID | Requirement |
|---|---|
| FR1 | The tab renders the most recent run across every shipped panel |
| FR2 | A run selector lists stored runs, newest first, and any run can be opened |
| FR3 | A verification control recomputes every hash and reports either an intact chain or the first run at which it breaks |
| FR4 | Each finding shows title, severity, confidence, ATT&CK technique and tactic, detail, evidence as literal observed records, and a concrete recommendation |
| FR5 | Each beacon assessment names both the benign and the malicious explanation |
| FR6 | Absence of collection is labelled as absence of collection and never presented as an all-clear. An hour with no run, or a run whose status is not `ok`, is shown as not covered |
| FR7 | Volume is shown only where the record carries measured byte counts. Otherwise the panel states that volume is unavailable, and no figure is estimated |
| FR8 | Demonstration mode is selected automatically when no real records are present, and is badged on the tab and in every panel that displays data |
| FR9 | Addresses, host names, hardware addresses and process arguments are masked by default, with a deliberate control to reveal them |
| FR10 | Timestamps are displayed with their original UTC offset and are never relabelled as UTC |
| FR11 | A record whose shape does not satisfy the schema is reported in the interface as a malformed record, and does not prevent other records from rendering |
| FR12 | The caveat notes in section 7.9 are displayed in full and are not collapsible by default |

### 6.2 Non-functional

| ID | Requirement |
|---|---|
| NFR1 | Standard library only. No bundler, no minifier, no vendored binary, no committed bytecode. Every source file is readable as committed |
| NFR2 | The tab loads nothing from an external host. No fonts, no scripts, no images, no stylesheets. Colour and type come from the dashboard theme variables |
| NFR3 | Route handlers never block the event loop. Use `async def` with `asyncio.to_thread`, or a plain `def` handler |
| NFR4 | A full run record is capped at 200 KiB, a trimmed record at `trimmed_max_bytes` (default 8 KiB), and every response is bounded in both size and count |
| NFR5 | The initial tab load transfers no more than one full record plus the run summaries |
| NFR6 | Tests complete in under one minute, with no network access and no OpenSnitch present |
| NFR7 | The tab is legible in both the light and the dark dashboard themes |

### 6.3 Security and privacy

| ID | Requirement |
|---|---|
| SP1 | Every route is a `GET` and is read-only. The plugin writes nothing beyond its own settings through Hermes |
| SP2 | The plugin never opens the OpenSnitch database. Only the collector does so, read-only, under the owner's own account |
| SP3 | Route parameters are validated against a strict pattern. No value supplied by a client reaches the filesystem as a path |
| SP4 | The plugin never reads `.env`, `auth.json`, browser profiles, key stores or any credential file |
| SP5 | Interface content is produced as React elements so that escaping is automatic. Raw markup injection is prohibited anywhere record data is rendered |
| SP6 | Synthetic data uses documentation ranges only: IPv4 192.0.2.0/24, 198.51.100.0/24 and 203.0.113.0/24 (RFC 5737), IPv6 2001:db8::/32 (RFC 3849), names under example.com and example.net (RFC 2606), and hardware addresses 00-00-5E-00-53-00 to 00-00-5E-00-53-FF (RFC 7042). A test fails the build if any fixture value falls outside these ranges |
| SP7 | The integrity feature is described honestly. It makes alteration detectable. It does not prove that records match the real network, and an adversary able to rewrite every record can recompute the chain |

## 7. Design

### 7.1 Components

```
 OpenSnitch statistics database        read-only, the owner's own account
            |
            v
 collector/snitchboard_collect.py      optional, run by the owner, never by Hermes
            |   one hash-chained JSON record per run
            v
 runs directory                        default <HERMES_HOME>/plugin-data/hermes-snitchboard/runs/
            |
            v
 dashboard/plugin_api.py  (GET only) -> dashboard/dist/index.js  (tab)
```

The viewer and the collector are separate by design. The component running inside the dashboard process never reaches the firewall database, which keeps its privileges small and supports hosts where Hermes runs under a different account from the owner.

### 7.2 Repository layout

The skeleton exists as of commit `41d3acb`.

```
.github/workflows/   tests, validation, history and fixture scans
dashboard/
  manifest.json      tab registration
  plugin_api.py      read-only routes, module-level `router`
  dist/index.js      hand-written IIFE, no build step
  dist/style.css     optional, theme variables only
snitchboard/         schema, canonical hashing, analysis, redaction
collector/
  snitchboard_collect.py
  systemd/           timer and service unit templates
fixtures/            synthetic records only
tools/               demonstration generator, scan scripts
tests/
docs/                this document, schema reference, security note, assets
plugin.yaml          manifest
__init__.py          minimal register(ctx) that registers nothing
```

### 7.3 Run record schema, version 1

Every record carries `schema_version`, `run_id`, `started_at`, `window_start`, `window_end`, `status`, `trimmed`, `note`, `coverage`, `totals` and `integrity`. Timestamps are ISO 8601 with an explicit offset.

`status` takes one of `ok`, `partial` or `no_data`. The reference implementation used `collection_unavailable`, which maps to `no_data`.

A record where `trimmed` is false additionally carries `detections`, `beacons`, `novel`, `agents`, `volume`, `rows` and `aggregates`. Every record, full or trimmed, carries `destinations`, a sorted list of the destinations observed. Novelty is computed against prior runs of either form, and a full record's `rows` and `hosts` are capped, so a full record that omitted this list would give a wrong rarity score. This extends the requirement identified in section 5.2.

A record where `trimmed` is true carries `detections` in shortened form. Every mandatory detection field is still present; only the prose is cut. Where a trimmed record would still exceed its cap, the lowest-severity detections are dropped and the record's `note` records that they were.

| Field | Shape |
|---|---|
| `coverage` | `{title, from, to, slots: [{label, covered}]}`, 24 slots |
| `totals` | `{connections, allowed, denied, unique_processes, unique_destinations, ai_connections, unattributed, novel_destinations, beacon_candidates, agents_active}`, all integers |
| `detections[]` | `{title, severity, confidence, attack: {technique, technique_id, tactic, tactic_id}, detail, evidence: [str], recommendation}`. All fields are mandatory; the partial form seen in section 5.1 is not permitted |
| `beacons[]` | `{process, destination, count, mean_interval, jitter_pct, confidence, assessment}` |
| `novel[]` | `{destination, rarity, contacts, processes, prior_runs_seen, baseline_note}` |
| `agents[]` | `{process, pid, user, connections, ports, destinations, privilege_note, verdict}` |
| `volume` | `{available: bool, note, rows: [{process, destination, sent_bytes, recv_bytes, flows, assessment}]}` |
| `rows[]` | `{ts, action, src, dst, dport, proto, uid, pid, process, activity, is_ai, severity}` |
| `aggregates` | `{daemon_uptime, total_connections, dropped, rules, procs[], hosts[], users[], ports[], addrs[], node{}, rules_detail[], sockets[]}`, where each aggregate list holds `{what, hits}` |
| `aggregates.node` | `{addr, hostname, daemon_version, daemon_uptime, daemon_rules, cons, cons_dropped, version, status, last_connection}` |
| `aggregates.rules_detail[]` | `{name, enabled, precedence, action, duration, operator_type, operator_operand, operator_data, created}` |
| `integrity` | `{content_sha256, prev_sha256, run_index}` |

Caps: 120 rows, 45 volume rows, 20 hosts, 15 addresses, 15 novel destinations, 16 beacons. The trimmed-record cap is the setting `trimmed_max_bytes`, default 8 KiB. A busy host can produce a destination list that will not fit, and trimming then fails loudly rather than discarding destinations silently, because a quietly shortened list would corrupt novelty with no signal that it had happened. Severity is one of `high`, `medium` or `low`. Confidence is one of `high`, `medium` or `low`. Default retention is fourteen days, after which a full record is trimmed rather than deleted, so the chain survives.

Integrity is the SHA-256 of the canonical JSON of the record with the `integrity` block removed, keys sorted, no whitespace. Trimming changes the content and therefore breaks the hash, so a trimmed record carries the original `content_sha256` unchanged in a `sealed_sha256` field and sets `trimmed` to true. Verification treats a trimmed record as a link whose content cannot be re-derived, states this plainly, and continues the chain.

What the chain does and does not cover is set out here, because the distinction decides what may honestly be claimed. The chain attests to the sequence of full records and to the digest each one held, and that fact survives trimming, because the successor's `prev_sha256` still matches the preserved `sealed_sha256`. A trimmed record's own summary content is not covered: an adversary who edited it and recomputed its digest would not be caught. Trimmed summaries are therefore derived analysis aids rather than evidence, they are classified as partial records in the interface, and editing one degrades novelty scoring without forging anything. Binding each trimmed form into its successor's canonical content would close the gap, and that is recorded as a candidate for a later version.

### 7.4 Analysis rules

Thresholds are configurable; the defaults follow.

| Analysis | Rule |
|---|---|
| Coverage | One slot per hour across the last 24 hours. An hour with no run, or whose run status is not `ok`, is not covered |
| Novelty | For each destination, count the prior runs, up to 48, that contained it. Rarity is 100 when never seen, scaling to 0 when present in every prior run. Report the top 15 |
| Beaconing | For each process and destination pair with at least eight contacts, excluding port 53, compute the mean interval and the jitter as a coefficient of variation in per cent. Report pairs whose mean falls between 20 seconds and 2 hours with jitter below 60 per cent, ordered by jitter. Confidence is high below 10 per cent, medium below 25 per cent, otherwise low. Every assessment states both the benign and the malicious reading. Services named in the expected list are labelled as expected rather than flagged. Eight contacts inside a one-hour window cap the observable mean interval at roughly 8.5 minutes, so the two-hour ceiling becomes reachable only once the collector supplies a longer lookback |
| Volume | Used only where the record carries measured per-flow byte counts joined to the owning process. Ranked by total bytes, capped at 45 rows, with an assessment derived from the sent and received ratio. A flow that opened before the window and could not be paired is labelled as such |
| Agents | One row for each configured AI process and each configured non-standard account, giving connections, ports, destinations, a privilege note and a verdict |
| Integrity | As specified in section 7.3 |

### 7.5 ATT&CK mapping

| Pattern | Technique | Tactic |
|---|---|---|
| Regular-interval outbound sessions | T1071 Application Layer Protocol | TA0011 Command and Control |
| Web-protocol application channels | T1071.001 Web Protocols | TA0011 |
| Unusual DNS volume or resolvers | T1071.004 DNS | TA0011 |
| Many distinct or unusual domains | T1568 Dynamic Resolution | TA0011 |
| Non-standard destination port, as a control channel | T1571 Non-Standard Port | TA0011 |
| Non-standard destination port, as an exfiltration channel | T1048 Exfiltration Over Alternative Protocol | TA0010 Exfiltration |
| Sustained transfer to a service endpoint | T1567 Exfiltration Over Web Service | TA0010 |
| An account used beyond its need | T1078 Valid Accounts | Not tied to a single tactic |

Two severity rules in 7.6 have no row of their own. An unattributed connection and a denied connection take the technique implied by their destination port, and T1078 carries a descriptive tactic with an empty `tactic_id`, because that technique spans several tactics. T1571 was verified against the ATT&CK site and is included on the owner's decision. A bundled list of permitted identifiers is checked by a test, so the engine cannot emit an identifier that is not on it. The remaining names are confirmed during the release checklist.

### 7.6 Severity

| Level | Default conditions |
|---|---|
| High | A connection with no attributable process. An AI process on a non-standard port. Any denied connection. A destination never previously seen, reached by AI tooling during configured unattended hours. Traffic from a configured agent account to a destination absent from its allowlist. An outbound-dominant transfer above 1 MB to an unidentified destination |
| Medium | A new destination for a known process. Third-party telemetry reached by AI tooling. High-confidence beaconing |
| Low | Anything else worth recording |

The provider allowlist replaces a blanket rule treating all agent-account traffic as high severity. Without it, every legitimate provider connection would be flagged, and the panel would be useless.

### 7.7 Backend routes

All routes sit beneath `/api/plugins/hermes-snitchboard/`, behind the dashboard authentication gate.

| Route | Returns |
|---|---|
| `GET /health` | Mode, the settings source, the runs directory path and its status, record count, schema version. The path is masked unless `reveal` is passed, because this route is the only way an operator can see it: the dashboard auth gate makes the endpoint unreadable from a browser address bar |
| `GET /settings` | Effective settings, excluding anything sensitive |
| `GET /runs?limit=&offset=` | Run summaries only: identifier, window, status, severity counts, trimmed flag. Bounded and paginated |
| `GET /runs/latest` | The most recent full record, redacted unless reveal is requested |
| `GET /runs/{run_id}` | One record. The identifier must match a fixed pattern |
| `GET /series?n=24` | Compact series for the chart: per-run connection, AI, denied and timestamp values |
| `GET /verify` | Recomputes the chain and reports an intact result or the first break |

### 7.8 Settings

Declared through `config_schema`: `runs_dir`, `mode` (`auto`, `demo`, `live`), `ai_process_names`, `agent_accounts`, `expected_services`, `provider_allowlist`, `unattended_hours`, `redact_by_default` (default true), `allow_reveal`, `retention_days` (default 14), `telemetry_destinations` (the list feeding the medium-severity rule in 7.6) and `trimmed_max_bytes` (default 8192, accepted range 1024 to 204800). Defaults are neutral and name no particular machine. Lowering `trimmed_max_bytes` marks records already trimmed under a larger cap as malformed, which is honest rather than silent, and the setting's description must say so.

### 7.9 Interface inventory and priority tiers

Build in tier order. A time squeeze drops the lowest tier rather than leaving everything unfinished.

**Tier A, must ship**

| # | Element | Content |
|---|---|---|
| 1 | Header | Run selector, mode badge, redaction toggle, last collection time |
| 2 | Summary | The ten totals, as a figure grid |
| 3 | Coverage | Twenty-four hourly slots, gaps shown as gaps |
| 4 | Findings | Detections with severity pill, confidence, ATT&CK block, detail, evidence and recommendation |
| 5 | Beacons | Process, destination, count, mean interval, jitter, confidence, assessment |
| 6 | Novel destinations | Destination, rarity, contacts, processes, prior runs seen |
| 7 | Agents | AI tooling and non-standard accounts, with privilege note and verdict |
| 8 | Integrity | Run hashes, chain position, and a verification control |
| 9 | Caveats | The eight notes below, in full |

The caveat notes, carried over because they are what separates a serious instrument from one that overclaims: remote content stays encrypted; local agent content is obtainable; more metadata exists than is collected; volume comes from connection tracking; collection is hourly; collection follows the desktop session; container attribution is unverified; detection confidence is not certainty.

**Tier B, should ship**

| # | Element | Content |
|---|---|---|
| 10 | Connections chart | Inline SVG, last 24 runs, split by AI traffic, other traffic and denied |
| 11 | Events | The ranked connection table, capped at 120 rows |
| 12 | Aggregates | Five sub-tables: destinations, processes, accounts, ports, addresses |

**Tier C, nice to have**

| # | Element | Content |
|---|---|---|
| 13 | Volume | Bytes sent and received per flow, with a per-row assessment |
| 14 | Daemon state | The node row as the collector reports it |
| 15 | Rules | Rules in force at collection time |
| 16 | Sockets | Live sockets, where socket monitoring is enabled |
| 17 | Export | CSV of the current run, generated in the browser from data already loaded |

### 7.10 Front-end conventions

These three decisions are binding and were taken deliberately.

**Elements, not markup strings.** Every panel is built with `SDK.React.createElement`, conventionally aliased to a short helper. React escapes automatically, which removes an entire class of injection risk arising from process names and host names flowing into the page. Raw markup injection is prohibited wherever record data is rendered. The sole exception is the chart, which is assembled from numeric values only and contains no text drawn from a record.

**A bounded data layer.** The tab requests run summaries and a single record, never the whole history. The chart is served by its own compact series route.

**Theme variables.** Colour, type and spacing come from the dashboard theme. No web font is loaded. SDK components provide the panel chrome so the tab looks native rather than transplanted, with custom markup inside each panel.

## 8. Constraints

| Type | Constraint |
|---|---|
| Time | The deadline is 22:00 UTC on Wednesday 11 November 2026, which is 09:00 on Thursday 12 November in the owner's timezone. Fifty-nine hours remained when this version was approved |
| Technical | Dashboard plugins use the SDK components and a single pre-built IIFE bundle. The SDK ships no chart component, so charts are inline SVG. Routes mount once at startup, so a route change requires a dashboard restart |
| Catalogue | One YAML file in the pull request. An exact forty-character SHA pin. No self-updating code, no compiled artefact or bytecode, no runtime override of core, a truthful `requires_hermes`, and declared capabilities that match what is registered |
| Disclosure | Reads outside the plugin's own data, background processes and network calls are disclosed in the pull request and the README. Telemetry must be opt-in. Version 1 has none |
| Compliance | No personal data and no traceable identifier in any published artefact |
| Platform | Linux only. Live data requires OpenSnitch. Demonstration mode runs wherever Hermes runs |

## 9. Build plan

### 9.1 Sequence

| Priority | Work |
|---|---|
| P0 | Schema module and validator. Canonical hashing and chain verification. Analysis engine with unit tests. Synthetic generator producing at least 24 runs, two full and the remainder trimmed. Range-checking fixture test. `plugin.yaml`, `__init__.py`, `dashboard/manifest.json` and an early validation run. `plugin_api.py`. Tier A panels. Redaction |
| P1 | Tier B panels. Reference collector and unit templates |
| P2 | Tier C panels. Banner refinements, screenshots, architecture diagram |

Run `hermes plugins validate . --install-deps` as soon as the manifest and `__init__.py` exist, before any interface work. Risks R1 and R2 are resolved by that first run rather than by assumption.

Never cut: redaction, demonstration mode, chain verification, the caveat notes, disclosure and tests.

### 9.2 Timeline

| When | Milestone |
|---|---|
| Tuesday 10 November, morning | Schema, hashing, engine and tests. First validation run |
| Tuesday, afternoon | Generator and fixtures. Backend routes. Tier A panels |
| Tuesday, evening | Tier B panels. Collector if time allows |
| Wednesday, morning | Tier C panels. Screenshots from demonstration data. History-wide scan. Repository made public once the gate in 11.3 passes |
| Wednesday, by 12:00 UTC | Release tagged, catalogue pull request opened |
| Wednesday, by 15:00 UTC | Video recorded and posted, tagging the organisers |
| Wednesday, by 18:00 UTC | Form submitted, leaving four hours of margin |

## 10. Test strategy

- Unit tests for every analysis rule, including boundary values: seven and eight contacts, 9.9 and 10 per cent jitter, 24.9 and 25 per cent, exactly 20 seconds and exactly 2 hours.
- Integrity tests: round trip, single-field edit, deleted run, reordered runs, and a trimmed record in the chain.
- Schema tests: every fixture validates; a record missing a mandatory detection field is rejected.
- Fixture range test: every address, hardware address and name lies inside the documentation ranges.
- API tests: a malformed identifier is rejected, response bounds hold, and no route accepts a path.
- Interface test: the tab renders against a fixture set in both themes, and a malformed record does not prevent other panels from rendering.
- Validation: `hermes plugins validate . --install-deps` and `hermes plugins doctor . --ci`, locally and in continuous integration, against the exact commit to be pinned.
- Manual: install into a clean Hermes profile, view demonstration mode, then live mode with a collected run.

## 11. Catalogue submission

### 11.1 Draft entry

```yaml
name: hermes-snitchboard
title: Hermes Snitchboard
repo: https://github.com/NeumannTechTips/hermes-snitchboard
sha: <forty characters, set at release>
description: "Dashboard-only: ..."   # carries the disclosure in 11.2
maintainer: NeumannTechTips
tier: community
category: general
requires_hermes: ">=0.23.0"
version: "0.1.0"
docs_url: https://github.com/NeumannTechTips/hermes-snitchboard#readme
image: <2:1 banner on raw.githubusercontent.com, pinned to the commit>
screenshots: [<up to six, from synthetic data, pinned to the commit>]
platforms: [linux]
capabilities:
  provides_tools: []
  provides_hooks: []
  provides_middleware: []
  requires_env: []
```

### 11.2 Disclosure

The plugin reads run-record files from one configured directory, read-only. It makes no network call, runs no background process, stores no credential and sends no telemetry. The optional collector is a separate script the owner runs under their own account; it reads the OpenSnitch statistics database read-only and writes run records. Hermes does not load the collector.

### 11.3 Publication gate

Every item must pass before the repository is made public.

1. Pattern scan of the entire git history for IPv4, IPv6 and hardware address formats, host and account names, home paths and the owner's real name. Any hit means the history is rewritten before publication.
2. Fixture range test passes.
3. Continuous integration logs reviewed, since workflow logs become public with the repository.
4. Every screenshot and the banner reviewed against the no-personal-data rule.
5. Branch protection and push rulesets re-enabled afterwards, because GitHub disables push rulesets when a repository becomes public.

## 12. Risks

| ID | Risk | Mitigation |
|---|---|---|
| R1 | The validator may require `__init__.py` beside `plugin.yaml` even for a dashboard-only plugin | Ship a minimal `register(ctx)` that registers nothing, and validate on the first morning |
| R2 | The documented way to read settings may differ between native code and a dashboard backend | Use the documented read-only helper, falling back to a settings file in the plugin data directory |
| R3 | Routes mount once at startup, so changes during testing need a restart | The restart is part of the test procedure |
| R4 | Seventeen interface elements is a large surface for the time available | Tier order in 9.1, with an explicit list of what is never cut |
| R5 | An identifier slips into history or an image | Strict ignore rules, fixture range test, history scan and manual review at the gate |
| R6 | OpenSnitch database layout varies between versions | The collector checks the schema first and records `no_data` or `partial` with an explanation rather than guessing |
| R7 | A reviewer sees overlap with application-layer tooling such as privacy-xray | The README states the distinction plainly: application tooling records what the agent sent, Hermes Snitchboard records what the operating system observed leaving |
| R8 | The project avatar is the Nous Research character mark, which a reviewer could read as implying endorsement | The unofficial notice sits directly beneath the header, and the README carries an explicit credit and non-endorsement statement. Replacing the avatar is a one-line change if a reviewer objects |

## 13. Open questions

| ID | Question | Default |
|---|---|---|
| OQ1 | Is `general` or `web` the better catalogue category for a dashboard-only plugin? | `general`, matching an existing dashboard-only entry |
| OQ2 | Which configuration helper is intended for a dashboard backend? | The documented read-only helper, with a file fallback |
| OQ3 | What is the documented default location of the OpenSnitch database? | None asserted. The collector requires an explicit path |
| OQ4 | Does the validator accept a dashboard-only plugin without `__init__.py`? | Ship the no-op `register(ctx)` regardless |
| OQ5 | Are the ATT&CK names for the remaining identifiers current? | Verified during the release checklist |

## 14. Decisions recorded

| ID | Decision | Date |
|---|---|---|
| D1 | Licence is MIT OR Apache-2.0, with NeumannTechTips as the copyright holder | 9 November 2026 |
| D2 | T1571 is added to the technique mapping, alongside T1048 for the exfiltration reading | 9 November 2026 |
| D3 | The viewer and the collector are separate components. The plugin reads a directory of records and never opens the firewall database. This supersedes the earlier assumption about cross-account file access, which no longer applies | 9 November 2026 |
| D4 | Full-fidelity port approved, built in the three tiers set out in 7.9 | 9 November 2026 |
| D5 | Interface built from React elements rather than markup strings, with a bounded data layer and dashboard theme variables | 9 November 2026 |
| D6 | The project avatar is used, with the non-endorsement statement in the README | 9 November 2026 |
| D7 | `destinations` is carried by both record forms, not by trimmed records alone | 9 November 2026 |
| D8 | The integrity claim is scoped to full records and to chain order. Trimmed summaries are derived aids rather than evidence, and the interface states this | 9 November 2026 |
| D9 | Trimming fails loudly when the destination list will not fit the cap. Storing destination digests instead is deferred to a later version | 9 November 2026 |
| D10 | A known process means one that can be identified, since trimmed history keeps no process names. A run with status `no_data` is excluded from the novelty denominator | 9 November 2026 |
| D11 | The plugin is called Hermes Snitchboard wherever a reader sees it, including the catalogue `title`. The short form is reserved for the directory and package name `hermes-snitchboard` | 10 November 2026 |
| D12 | The connections chart draws one column per stored run, so an hour with no run at all is absent from it rather than shown as zero. The coverage strip is the panel that answers that question, and the chart caption says so | 10 November 2026 |

## 15. Sources

- Hermes Agent, extending the dashboard: https://hermes-agent.nousresearch.com/docs/user-guide/features/extending-the-dashboard
- Hermes Agent, plugin developer guide: https://hermes-agent.nousresearch.com/docs/developer-guide/plugins
- Hermes Agent, submitting to the plugin catalogue: https://hermes-agent.nousresearch.com/docs/developer-guide/plugins/catalog-submission
- Plugin catalogue entry schema: https://github.com/NousResearch/hermes-agent/blob/main/plugin-catalog/README.md
- OpenSnitch: https://github.com/evilsocket/opensnitch
- MITRE ATT&CK, T1571 Non-Standard Port: https://attack.mitre.org/techniques/T1571/
- RFC 5737, IPv4 blocks reserved for documentation: https://www.rfc-editor.org/rfc/rfc5737
- RFC 3849, IPv6 prefix reserved for documentation: https://www.rfc-editor.org/rfc/rfc3849
- RFC 2606, reserved DNS names: https://www.rfc-editor.org/rfc/rfc2606
- RFC 7042, documentation hardware address values, replaced by RFC 9542: https://www.rfc-editor.org/rfc/rfc7042
- GitHub, setting repository visibility: https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility

## 16. Change record

| Date | Version | Change |
|---|---|---|
| 9 November 2026 | 0.1 | Draft created for sign-off |
| 10 November 2026 | 1.2 | Resolutions from the third build session: the full name adopted everywhere a reader sees it, NFR4 aligned with the `trimmed_max_bytes` setting, the `/health` description corrected, the cap-lowering consequence recorded, and decisions D11 and D12 added |
| 9 November 2026 | 1.1 | Resolutions from the first build session recorded: SC6 scoped to full records and chain order, `destinations` carried by both forms, trimmed detections shortened rather than reduced, `telemetry_destinations` and `trimmed_max_bytes` added to 7.8, the beacon ceiling limitation noted, and decisions D7 to D10 added |
| 9 November 2026 | 1.0 | Approved. Scope widened to a full-fidelity port with seventeen interface elements in three tiers. Section 5 added, recording schema inconsistency and the trimming effect on novelty. Schema in 7.3 made strict, with a declared trimmed form. Front-end conventions added at 7.10. Routes extended with pagination and a series endpoint. Decisions D1 to D6 recorded. The earlier assumptions about cross-account access are closed by D3 |
