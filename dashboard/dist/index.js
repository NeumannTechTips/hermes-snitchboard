/*
 * Hermes Snitchboard dashboard tab, Tiers A, B and C (HSB-PRD-001 sections 7.9
 * and 7.10).
 *
 * Hand-written, no build step. React comes from the dashboard SDK and is
 * never bundled. Every element is made with React.createElement, so record
 * text such as process and host names is escaped by React. Nothing here
 * assigns markup strings, and nothing is loaded from another host. Colour,
 * type and spacing come from the dashboard theme variables.
 */
(function () {
  "use strict";

  var SDK = window.__HERMES_PLUGIN_SDK__;
  var registry = window.__HERMES_PLUGINS__;
  if (!SDK || !SDK.React || !registry || typeof registry.register !== "function") {
    if (window.console) {
      window.console.warn("hermes-snitchboard: the dashboard plugin SDK is unavailable");
    }
    return;
  }

  var React = SDK.React;
  var h = React.createElement;
  var hooks = SDK.hooks || React;
  var useState = hooks.useState;
  var useEffect = hooks.useEffect;
  var useCallback = hooks.useCallback;
  var components = SDK.components || {};

  var PLUGIN = "hermes-snitchboard";
  var API = "/api/plugins/" + PLUGIN;
  var RUNS_PAGE = 50;
  var SERIES_RUNS = 24;

  // An SDK component when present, otherwise a plain element with the same
  // children, so a missing component degrades rather than breaking the tab.
  function part(name, tag) {
    var component = components[name];
    if (component) return component;
    return function (props) {
      var rest = {};
      Object.keys(props || {}).forEach(function (key) {
        if (key !== "variant" && key !== "size") rest[key] = props[key];
      });
      return h(tag, rest);
    };
  }

  var Card = part("Card", "section");
  var CardHeader = part("CardHeader", "div");
  var CardTitle = part("CardTitle", "h3");
  var CardContent = part("CardContent", "div");
  var Badge = part("Badge", "span");
  var Button = part("Button", "button");

  // ------------------------------------------------------------ theme

  function token(name) {
    return "var(--color-" + name + ", currentColor)";
  }

  var C = {
    text: "inherit",
    muted: token("muted-foreground"),
    border: "var(--color-border, currentColor)",
    surface: "var(--color-muted, transparent)",
    high: token("destructive"),
    medium: token("warning"),
    low: token("muted-foreground"),
    good: token("success"),
    primary: token("primary")
  };

  function sp(units) {
    return "calc(" + (units * 0.25) + "rem * var(--spacing-mul, 1))";
  }

  function tint(colour, percent) {
    return "color-mix(in srgb, " + colour + " " + percent + "%, transparent)";
  }

  var S = {
    stack: { display: "flex", flexDirection: "column", gap: sp(4) },
    row: { display: "flex", flexWrap: "wrap", alignItems: "center", gap: sp(2) },
    small: { fontSize: "0.8125rem", color: C.muted },
    para: { margin: 0, lineHeight: 1.5 },
    mono: { overflowWrap: "anywhere" },
    tableWrap: { overflowX: "auto", maxWidth: "100%" },
    table: { width: "100%", borderCollapse: "collapse", fontSize: "0.875rem" },
    th: {
      textAlign: "left", fontWeight: 600, padding: sp(2), color: C.muted,
      borderBottom: "1px solid " + C.border, whiteSpace: "nowrap"
    },
    td: { padding: sp(2), borderBottom: "1px solid " + C.border, verticalAlign: "top" },
    notice: {
      border: "1px solid " + C.border, borderRadius: "var(--radius, 0.5rem)",
      padding: sp(3), background: C.surface, margin: 0, lineHeight: 1.5
    },
    select: {
      font: "inherit", color: "inherit", background: "transparent",
      border: "1px solid " + C.border, borderRadius: "var(--radius, 0.5rem)",
      padding: sp(1.5) + " " + sp(2), maxWidth: "100%"
    }
  };

  // ------------------------------------------------------- formatting

  // Timestamps keep the offset they were recorded with (FR10). Only the T
  // separator is replaced; no conversion to the browser's zone takes place.
  function stamp(value) {
    if (typeof value !== "string" || !value) return "unknown";
    return value.replace("T", " ");
  }

  function count(value) {
    return typeof value === "number" ? value.toLocaleString("en-GB") : "n/a";
  }

  function interval(seconds) {
    if (typeof seconds !== "number") return "n/a";
    if (seconds < 60) return seconds.toFixed(1) + " s";
    var minutes = Math.floor(seconds / 60);
    var rest = Math.round(seconds - minutes * 60);
    if (minutes < 60) return minutes + " min " + rest + " s";
    return Math.floor(minutes / 60) + " h " + (minutes % 60) + " min";
  }

  function percent(value) {
    return typeof value === "number" ? value.toFixed(1) + "%" : "n/a";
  }

  function list(values) {
    return Array.isArray(values) && values.length ? values.join(", ") : "none";
  }

  // ----------------------------------------------------------- pieces

  var DEMO_LABEL = "Demonstration data";
  var NOT_HELD = "Not held in this record.";
  var TRIMMED_GAP = NOT_HELD + " Trimmed records keep only the summary, the " +
    "shortened findings and the destination list.";
  var SECTION_ABSENT = NOT_HELD + " The record does not carry this section.";

  // Fallbacks for the caps the server reports under /settings. They mirror
  // the schema caps in the engine's schema module and its aggregate cap.
  var CAPS_FALLBACK = {
    rows: 120, volume_rows: 45, hosts: 20, addrs: 15, novel: 15, beacons: 16,
    aggregates: 20
  };

  function capOf(caps, key) {
    var value = caps && caps[key];
    return typeof value === "number" && value > 0 ? value : CAPS_FALLBACK[key];
  }

  // Why a section is missing: trimmed by design, or absent from the record.
  function gapText(record) {
    return record && record.trimmed ? TRIMMED_GAP : SECTION_ABSENT;
  }

  function Pill(props) {
    var colour = C[props.level] || C.low;
    return h("span", {
      style: {
        display: "inline-block", padding: "0 " + sp(2), borderRadius: "999px",
        border: "1px solid " + colour, color: colour, background: tint(colour, 12),
        fontSize: "0.75rem", fontWeight: 600, lineHeight: 1.6,
        textTransform: "uppercase", letterSpacing: "0.03em", whiteSpace: "nowrap"
      }
    }, props.children);
  }

  function DemoBadge(props) {
    if (!props.demo) return null;
    return h(Badge, { variant: "outline", style: { borderColor: C.medium, color: C.medium } },
      DEMO_LABEL);
  }

  function Panel(props) {
    return h(Card, { "data-snitchboard-panel": props.id },
      h(CardHeader, null,
        h("div", { style: Object.assign({}, S.row, { justifyContent: "space-between" }) },
          h(CardTitle, null, props.title),
          h("div", { style: S.row }, h(DemoBadge, { demo: props.demo }), props.extra || null))),
      h(CardContent, null, h("div", { style: S.stack }, props.children)));
  }

  // One panel failing to draw must not take the others with it (FR11).
  function PanelGuard(props) {
    React.Component.call(this, props);
    this.state = { failure: null };
  }
  PanelGuard.prototype = Object.create(React.Component.prototype);
  PanelGuard.prototype.constructor = PanelGuard;
  PanelGuard.getDerivedStateFromError = function (error) {
    return { failure: String((error && error.message) || error) };
  };
  PanelGuard.prototype.render = function () {
    if (this.state.failure) {
      return h(Panel, { id: "failed", title: this.props.title },
        h("p", { style: S.notice }, "This panel could not be drawn: " + this.state.failure));
    }
    return this.props.children;
  };

  function Note(props) {
    return h("p", { style: S.notice }, props.children);
  }

  function Muted(props) {
    return h("p", { style: Object.assign({}, S.para, S.small) }, props.children);
  }

  function Mono(props) {
    return h("span", { className: "font-mono", style: S.mono }, props.children);
  }

  function Table(props) {
    var columns = props.columns;
    return h("div", { style: S.tableWrap },
      h("table", { style: S.table },
        h("thead", null, h("tr", null, columns.map(function (col) {
          return h("th", { key: col.key, style: S.th, scope: "col" }, col.label);
        }))),
        h("tbody", null, props.rows.map(function (row, index) {
          return h("tr", { key: index }, columns.map(function (col) {
            var value = col.render ? col.render(row) : row[col.key];
            return h("td", { key: col.key, style: S.td }, value);
          }));
        }))));
  }

  // ------------------------------------------------------- 1 header

  function runLabel(run) {
    if (run.malformed) return run.run_id + " (malformed record)";
    var form = run.trimmed ? "trimmed summary" : "full record";
    return stamp(run.started_at) + " · " + run.status + " · " + form;
  }

  var SOURCE_LABELS = {
    hermes: "the Hermes configuration",
    file: "settings.json in the plugin data directory",
    defaults: "built-in defaults"
  };

  var DEMO_RANGES = "Every address and name in it comes from the ranges " +
    "reserved for documentation.";

  // The operator cannot read /health through the browser because of the
  // dashboard's authentication gate, so where the settings came from and
  // which runs directory was resolved are stated here instead.
  function SettingsLine(props) {
    var health = props.health;
    if (!health) return null;
    var source = health.settings_source;
    var from = source ? "Settings from " + (SOURCE_LABELS[source] || String(source)) + "." :
      "The settings source was not reported.";
    var dir = health.runs_dir;
    var problems = Array.isArray(health.settings_problems) ? health.settings_problems : [];
    return h("div", { style: S.stack },
      h(Muted, null, from,
        dir ? " Runs directory (" + (dir.location || "unknown") + ", " +
          String(dir.status || "unknown").replace(/_/g, " ") + "): " : null,
        dir ? h(Mono, null, dir.path || "path not reported") : null,
        dir ? "." : null),
      problems.map(function (problem, index) {
        return h(Note, { key: index }, "Settings problem: " + problem);
      }));
  }

  function Header(props) {
    var health = props.health || {};
    var payload = props.payload;
    var runs = props.runs;
    var demo = !!health.demo;
    var newest = runs.items.length ? runs.items[0] : null;
    var lastCollected = newest && !newest.malformed ? stamp(newest.started_at) :
      (newest ? "newest record is malformed" : "no records");
    var malformed = runs.items.filter(function (r) { return r.malformed; });
    var revealed = payload && payload.revealed;
    var canReveal = props.settings && props.settings.allow_reveal;
    var record = payload && payload.record;

    var modeBadge = h(Badge, {
      variant: "outline",
      style: { borderColor: demo ? C.medium : C.good, color: demo ? C.medium : C.good }
    }, demo ? DEMO_LABEL : "Live data");

    var selector = h("label", { style: S.row },
      h("span", { style: S.small }, "Run"),
      h("select", {
        style: S.select, value: props.selected || "",
        onChange: function (event) { props.onSelect(event.target.value || null); }
      },
        h("option", { value: "" }, "Most recent full record"),
        runs.items.map(function (run) {
          return h("option", { key: run.run_id, value: run.run_id }, runLabel(run));
        })));

    var more = runs.items.length < runs.total ? h(Button, {
      variant: "outline", size: "sm", onClick: props.onMore, disabled: props.loadingMore
    }, "Load older runs") : null;

    var toggle = canReveal ? h(Button, {
      variant: revealed ? "destructive" : "outline", size: "sm",
      disabled: !payload || payload.malformed, onClick: props.onToggleReveal,
      "aria-pressed": !!revealed
    }, revealed ? "Mask values" : "Reveal values") : null;

    return h(Card, { "data-snitchboard-panel": "header" },
      h(CardHeader, null,
        h("div", { style: Object.assign({}, S.row, { justifyContent: "space-between" }) },
          // The theme sets panel titles in capitals; the plugin's name keeps
          // its own case. The span covers an SDK title that ignores style.
          h(CardTitle, { style: { textTransform: "none" } },
            h("span", { style: { textTransform: "none" } }, "Hermes Snitchboard")),
          h("div", { style: S.row }, modeBadge,
            h(Badge, { variant: "outline" }, revealed ? "Values revealed" : "Values masked")))),
      h(CardContent, null,
        h("div", { style: S.stack },
          h("div", { style: S.row }, selector, more, toggle,
            record ? h(ExportButton, { record: record, revealed: !!revealed }) : null),
          h("div", { style: S.row },
            h(Muted, null, "Last collection: " + lastCollected),
            record ? h(Muted, null, "Showing " + record.run_id + ", window " +
              stamp(record.window_start) + " to " + stamp(record.window_end)) : null),
          demo ? h(Note, null, (health.mode_setting === "demo" ?
            "The mode setting asks for demonstration data, so the tab is showing " +
            "synthetic records whatever the runs directory holds. " :
            "No run records were found, so the tab is showing synthetic " +
            "demonstration data. ") + DEMO_RANGES) : null,
          h(SettingsLine, { health: props.health }),
          record && record.status !== "ok" ? h(Note, null, "This run has status " +
            record.status + ". " + (record.note || "") +
            " Its hour is shown as not covered, not as quiet.") : null,
          record && record.trimmed ? h(Note, null, "This is a trimmed record, a " +
            "partial record kept after retention. Detail panels are empty by design, " +
            "and its summary is not covered by the hash chain.") : null,
          malformed.length ? h(Note, null, malformed.length + " stored record(s) " +
            "listed here are malformed and cannot be shown: " +
            malformed.map(function (r) { return r.run_id; }).join(", ") +
            ". The others are unaffected.") : null,
          payload && payload.skipped_malformed && payload.skipped_malformed.length ?
            h(Muted, null, "Newer malformed record(s) skipped: " +
              payload.skipped_malformed.join(", ")) : null)));
  }

  // ------------------------------------------------------ 2 summary

  var TOTALS = [
    ["connections", "Connections"], ["allowed", "Allowed"], ["denied", "Denied"],
    ["unique_processes", "Processes"], ["unique_destinations", "Destinations"],
    ["ai_connections", "AI connections"], ["unattributed", "Unattributed"],
    ["novel_destinations", "Novel destinations"],
    ["beacon_candidates", "Beacon candidates"], ["agents_active", "Active agents"]
  ];

  function Summary(props) {
    var totals = props.record.totals || {};
    return h(Panel, { id: "summary", title: "Summary", demo: props.demo },
      h("div", {
        style: {
          display: "grid", gap: sp(3),
          gridTemplateColumns: "repeat(auto-fill, minmax(8.5rem, 1fr))"
        }
      }, TOTALS.map(function (pair) {
        var value = totals[pair[0]];
        var alarm = (pair[0] === "denied" || pair[0] === "unattributed") && value > 0;
        return h("figure", {
          key: pair[0],
          style: {
            margin: 0, padding: sp(3), borderRadius: "var(--radius, 0.5rem)",
            border: "1px solid " + (alarm ? C.high : C.border), background: C.surface
          }
        },
          h("div", {
            style: { fontSize: "1.5rem", fontWeight: 700, color: alarm ? C.high : C.text }
          }, count(value)),
          h("figcaption", { style: S.small }, pair[1]));
      })));
  }

  // ----------------------------------------------------- 3 coverage

  function Coverage(props) {
    var coverage = props.record.coverage || {};
    var slots = Array.isArray(coverage.slots) ? coverage.slots : [];
    var gaps = slots.filter(function (s) { return !s.covered; });
    return h(Panel, { id: "coverage", title: coverage.title || "Coverage", demo: props.demo },
      h(Muted, null, "From " + stamp(coverage.from) + " to " + stamp(coverage.to) +
        ". An hour without a run, or whose run did not complete, is a gap in " +
        "collection and says nothing about what happened in it."),
      h("div", {
        role: "list",
        style: { display: "grid", gridTemplateColumns: "repeat(24, minmax(0, 1fr))", gap: "2px" }
      }, slots.map(function (slot, index) {
        return h("div", {
          key: index, role: "listitem",
          title: slot.label + (slot.covered ? " covered" : " not covered"),
          "aria-label": slot.label + (slot.covered ? " covered" : " not covered"),
          style: {
            height: "1.75rem", borderRadius: "3px",
            background: slot.covered ? tint(C.good, 55) : "transparent",
            border: slot.covered ? "1px solid " + tint(C.good, 80) : "1px dashed " + C.muted
          }
        });
      })),
      h("div", { style: Object.assign({}, S.row, { justifyContent: "space-between" }) },
        h("span", { style: S.small }, slots.length ? slots[0].label : ""),
        h("span", { style: S.small }, slots.length ? slots[slots.length - 1].label : "")),
      h(Muted, null, gaps.length ?
        gaps.length + " of " + slots.length + " hours not covered: " +
          gaps.map(function (s) { return s.label; }).join(", ") + "." :
        "Every hour in this window has a completed run."));
  }

  // ----------------------------------------------------- 4 findings

  function AttackBlock(props) {
    var a = props.attack || {};
    return h("div", {
      style: Object.assign({}, S.notice, { display: "grid", gap: sp(1), padding: sp(2) })
    },
      h("div", null, h("span", { style: S.small }, "Technique "),
        h(Mono, null, a.technique_id || "n/a"), " " + (a.technique || "")),
      h("div", null, h("span", { style: S.small }, "Tactic "),
        a.tactic_id ? h(Mono, null, a.tactic_id) : null,
        (a.tactic_id ? " " : "") + (a.tactic || "") +
          (a.tactic_id ? "" : " (this technique spans several tactics)")));
  }

  function Finding(props) {
    var d = props.detection;
    return h("article", {
      style: {
        borderLeft: "3px solid " + (C[d.severity] || C.low), paddingLeft: sp(3),
        display: "flex", flexDirection: "column", gap: sp(2)
      }
    },
      h("div", { style: S.row },
        h(Pill, { level: d.severity }, d.severity),
        h("span", { style: S.small }, "Confidence " + d.confidence)),
      h("h4", { style: { margin: 0, fontSize: "1rem", fontWeight: 600 } }, d.title),
      h(AttackBlock, { attack: d.attack }),
      h("p", { style: S.para }, d.detail),
      h("div", null,
        h("div", { style: S.small }, "Evidence, as observed"),
        h("ul", { style: { margin: 0, paddingLeft: sp(5) } },
          (d.evidence || []).map(function (line, index) {
            return h("li", { key: index, style: { fontSize: "0.8125rem" } }, h(Mono, null, line));
          }))),
      h("p", { style: S.para },
        h("span", { style: { fontWeight: 600 } }, "Recommendation: "), d.recommendation));
  }

  function Findings(props) {
    var detections = props.record.detections || [];
    var tally = { high: 0, medium: 0, low: 0 };
    detections.forEach(function (d) { tally[d.severity] = (tally[d.severity] || 0) + 1; });
    var extra = h("div", { style: S.row },
      h(Pill, { level: "high" }, tally.high + " high"),
      h(Pill, { level: "medium" }, tally.medium + " medium"),
      h(Pill, { level: "low" }, tally.low + " low"));
    return h(Panel, { id: "findings", title: "Findings", demo: props.demo, extra: extra },
      props.record.trimmed ? h(Muted, null, "Findings in a trimmed record are " +
        "shortened; the full prose was discarded at trimming.") : null,
      detections.length ? detections.map(function (d, index) {
        return h(Finding, { key: index, detection: d });
      }) : h(Muted, null, props.record.status === "ok" ?
        "No findings in this run." :
        "No findings, because collection did not complete for this run."));
  }

  // ------------------------------------------------------ 5 beacons

  function Beacons(props) {
    var record = props.record;
    return h(Panel, { id: "beacons", title: "Beacons", demo: props.demo },
      record.trimmed ? h(Muted, null, TRIMMED_GAP) :
        !record.beacons || !record.beacons.length ?
          h(Muted, null, "No process and destination pair met the beaconing thresholds.") :
          h(Table, {
            rows: record.beacons,
            columns: [
              { key: "process", label: "Process", render: function (r) { return h(Mono, null, r.process); } },
              { key: "destination", label: "Destination", render: function (r) { return h(Mono, null, r.destination); } },
              { key: "count", label: "Count", render: function (r) { return count(r.count); } },
              { key: "mean_interval", label: "Mean interval", render: function (r) { return interval(r.mean_interval); } },
              { key: "jitter_pct", label: "Jitter", render: function (r) { return percent(r.jitter_pct); } },
              { key: "confidence", label: "Confidence", render: function (r) { return h(Pill, { level: r.confidence === "high" ? "medium" : "low" }, r.confidence); } },
              { key: "assessment", label: "Assessment", render: function (r) { return h("span", { style: { lineHeight: 1.5 } }, r.assessment); } }
            ]
          }));
  }

  // -------------------------------------------------------- 6 novel

  function Novel(props) {
    var record = props.record;
    return h(Panel, { id: "novel", title: "Novel destinations", demo: props.demo },
      record.trimmed ? h(Muted, null, TRIMMED_GAP) :
        !record.novel || !record.novel.length ?
          h(Muted, null, "Every destination in this run was seen in earlier runs.") :
          h(Table, {
            rows: record.novel,
            columns: [
              { key: "destination", label: "Destination", render: function (r) { return h(Mono, null, r.destination); } },
              { key: "rarity", label: "Rarity", render: function (r) { return h(Pill, { level: r.rarity >= 100 ? "high" : r.rarity >= 50 ? "medium" : "low" }, String(r.rarity)); } },
              { key: "contacts", label: "Contacts", render: function (r) { return count(r.contacts); } },
              { key: "processes", label: "Processes", render: function (r) { return h(Mono, null, list(r.processes)); } },
              { key: "prior_runs_seen", label: "Prior runs seen", render: function (r) {
                return h("span", null, count(r.prior_runs_seen),
                  h("div", { style: S.small }, r.baseline_note));
              } }
            ]
          }));
  }

  // ------------------------------------------------------- 7 agents

  function Agents(props) {
    var record = props.record;
    return h(Panel, { id: "agents", title: "Agents", demo: props.demo },
      record.trimmed ? h(Muted, null, TRIMMED_GAP) :
        !record.agents || !record.agents.length ?
          h(Muted, null, "No configured AI process or agent account was active in this run.") :
          h(Table, {
            rows: record.agents,
            columns: [
              { key: "process", label: "Process", render: function (r) { return h(Mono, null, r.process || "unattributed"); } },
              { key: "pid", label: "PID", render: function (r) { return r.pid === null ? "n/a" : String(r.pid); } },
              { key: "user", label: "Account", render: function (r) { return h(Mono, null, r.user); } },
              { key: "connections", label: "Connections", render: function (r) { return count(r.connections); } },
              { key: "ports", label: "Ports", render: function (r) { return list(r.ports); } },
              { key: "destinations", label: "Destinations", render: function (r) { return h(Mono, null, list(r.destinations)); } },
              { key: "privilege_note", label: "Privilege", render: function (r) { return r.privilege_note; } },
              { key: "verdict", label: "Verdict", render: function (r) { return r.verdict; } }
            ]
          }));
  }

  // ---------------------------------------------- 10 connections chart

  // Drawn as SVG elements from numbers only. Each series carries a second
  // cue besides colour: AI traffic is hatched, other traffic is solid, and
  // denied connections are a dashed line with square markers.
  var CHART = { width: 720, height: 280, left: 52, right: 14, top: 16, bottom: 64 };
  var chartSeq = 0;

  function clock(value) {
    var match = typeof value === "string" ? /T(\d{2}):(\d{2})/.exec(value) : null;
    return match ? match[1] + ":" + match[2] : "?";
  }

  function niceStep(raw) {
    if (!(raw > 0)) return 1;
    var power = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
    var fraction = raw / power;
    var step = (fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10) * power;
    return Math.max(1, step);
  }

  function pointKind(point) {
    if (!point || point.malformed || typeof point.connections !== "number") return "malformed";
    if (point.status === "no_data") return "no_data";
    if (point.status === "partial") return "partial";
    return "ok";
  }

  function Glyph(props) {
    var body;
    if (props.kind === "ai") {
      body = h("rect", { x: 1, y: 1, width: 12, height: 12, style: { fill: "url(#" + props.hatch + ")", stroke: C.primary } });
    } else if (props.kind === "other") {
      body = h("rect", { x: 1, y: 1, width: 12, height: 12, style: { fill: tint(C.muted, 45), stroke: C.muted } });
    } else if (props.kind === "denied") {
      body = h("g", null,
        h("line", { x1: 0, y1: 7, x2: 14, y2: 7, strokeDasharray: "3 2", style: { stroke: C.high, strokeWidth: 2 } }),
        h("rect", { x: 4, y: 4, width: 6, height: 6, style: { fill: C.high } }));
    } else if (props.kind === "no_data") {
      body = h("rect", { x: 1, y: 1, width: 12, height: 12, strokeDasharray: "3 2", style: { fill: "none", stroke: C.muted } });
    } else if (props.kind === "malformed") {
      body = h("g", null,
        h("rect", { x: 1, y: 1, width: 12, height: 12, strokeDasharray: "1 2", style: { fill: "none", stroke: C.medium } }),
        h("line", { x1: 3, y1: 3, x2: 11, y2: 11, style: { stroke: C.medium } }),
        h("line", { x1: 11, y1: 3, x2: 3, y2: 11, style: { stroke: C.medium } }));
    } else if (props.kind === "partial") {
      body = h("rect", { x: 1, y: 1, width: 12, height: 12, strokeDasharray: "4 2", style: { fill: tint(C.muted, 45), stroke: C.medium, strokeWidth: 1.5 } });
    } else {
      body = h("rect", { x: 0, y: 0, width: 14, height: 14, style: { fill: tint(C.primary, 14) } });
    }
    return h("svg", { width: 14, height: 14, viewBox: "0 0 14 14", "aria-hidden": "true", focusable: "false" }, body);
  }

  function LegendItem(props) {
    return h("span", { style: Object.assign({}, S.row, { gap: sp(1) }) },
      h(Glyph, { kind: props.kind, hatch: props.hatch }),
      h("span", { style: S.small }, props.label));
  }

  function ChartSvg(props) {
    var points = props.points;
    var ids = props.ids;
    var plotW = CHART.width - CHART.left - CHART.right;
    var plotH = CHART.height - CHART.top - CHART.bottom;
    var slot = plotW / points.length;
    var barW = Math.max(2, slot * 0.62);
    var peak = 0;
    points.forEach(function (p) {
      if (pointKind(p) === "ok" || pointKind(p) === "partial") {
        peak = Math.max(peak, p.connections, p.denied || 0);
      }
    });
    var step = niceStep(peak / 4);
    var top = Math.max(step, Math.ceil(peak / step) * step);
    function y(value) { return CHART.top + plotH - (value / top) * plotH; }
    function x(index) { return CHART.left + slot * index + slot / 2; }
    var labelEvery = Math.max(1, Math.ceil(points.length / 8));
    var baseline = CHART.top + plotH;
    var nodes = [];

    nodes.push(h("defs", { key: "defs" },
      h("pattern", {
        id: ids.hatch, patternUnits: "userSpaceOnUse", width: 6, height: 6,
        patternTransform: "rotate(45)"
      },
        h("rect", { width: 6, height: 6, style: { fill: tint(C.primary, 22) } }),
        h("line", { x1: 0, y1: 0, x2: 0, y2: 6, style: { stroke: C.primary, strokeWidth: 3 } }))));

    for (var t = 0; t <= top; t += step) {
      nodes.push(h("g", { key: "y" + t },
        h("line", {
          x1: CHART.left, x2: CHART.width - CHART.right, y1: y(t), y2: y(t),
          style: { stroke: C.border, strokeWidth: t === 0 ? 1 : 0.5 }
        }),
        h("text", {
          x: CHART.left - 6, y: y(t) + 4, textAnchor: "end", fontSize: 11,
          style: { fill: "currentColor" }
        }, String(t))));
    }

    points.forEach(function (p, index) {
      var kind = pointKind(p);
      var cx = x(index);
      var left = cx - barW / 2;
      var children = [];
      if (props.selected && p.run_id === props.selected) {
        children.push(h("rect", {
          key: "sel", x: cx - slot / 2, y: CHART.top, width: slot, height: plotH,
          "data-selected": "true", style: { fill: tint(C.primary, 14) }
        }));
      }
      if (kind === "no_data" || kind === "malformed") {
        children.push(h("rect", {
          key: "gap", x: left, y: CHART.top, width: barW, height: plotH,
          "data-gap": kind, "data-run": p.run_id,
          strokeDasharray: kind === "no_data" ? "4 3" : "1 3",
          style: { fill: "none", stroke: kind === "no_data" ? C.muted : C.medium }
        }));
        children.push(h("text", {
          key: "gaptext", x: cx, y: CHART.top + plotH / 2, textAnchor: "middle",
          fontSize: 10, transform: "rotate(-90 " + cx + " " + (CHART.top + plotH / 2) + ")",
          style: { fill: kind === "no_data" ? C.muted : C.medium }
        }, kind === "no_data" ? "no data" : "malformed"));
      } else {
        var ai = Math.max(0, Math.min(p.ai_connections || 0, p.connections));
        var other = Math.max(0, p.connections - ai);
        children.push(h("rect", {
          key: "ai", x: left, y: y(ai), width: barW, height: baseline - y(ai),
          "data-part": "ai", "data-run": p.run_id,
          style: { fill: "url(#" + ids.hatch + ")", stroke: C.primary, strokeWidth: 0.5 }
        }));
        children.push(h("rect", {
          key: "other", x: left, y: y(ai + other), width: barW, height: y(ai) - y(ai + other),
          "data-part": "other", "data-run": p.run_id,
          style: { fill: tint(C.muted, 45), stroke: C.muted, strokeWidth: 0.5 }
        }));
        if (kind === "partial") {
          children.push(h("rect", {
            key: "partial", x: left - 1.5, y: y(p.connections) - 1.5, width: barW + 3,
            height: baseline - y(p.connections) + 1.5, strokeDasharray: "4 2",
            "data-partial": p.run_id,
            style: { fill: "none", stroke: C.medium, strokeWidth: 1.5 }
          }));
        }
      }
      if (index % labelEvery === 0) {
        children.push(h("text", {
          key: "tick", x: cx, y: baseline + 16, textAnchor: "middle", fontSize: 11,
          style: { fill: "currentColor" }
        }, kind === "malformed" && !p.started_at ? "?" : clock(p.started_at)));
        if (index === 0 && typeof p.started_at === "string") {
          children.push(h("text", {
            key: "date", x: cx, y: baseline + 30, textAnchor: "middle", fontSize: 10,
            style: { fill: C.muted }
          }, p.started_at.slice(0, 10)));
        }
      }
      nodes.push(h("g", { key: "p" + index }, children));
    });

    // The denied line breaks wherever a run carries no figures.
    var segments = [], current = [];
    points.forEach(function (p, index) {
      var kind = pointKind(p);
      if (kind === "ok" || kind === "partial") {
        current.push([x(index), y(p.denied || 0)]);
      } else if (current.length) {
        segments.push(current);
        current = [];
      }
    });
    if (current.length) segments.push(current);
    segments.forEach(function (segment, index) {
      if (segment.length > 1) {
        nodes.push(h("polyline", {
          key: "deny" + index, "data-series": "denied",
          points: segment.map(function (pair) { return pair[0] + "," + pair[1]; }).join(" "),
          strokeDasharray: "5 3", style: { fill: "none", stroke: C.high, strokeWidth: 1.75 }
        }));
      }
      segment.forEach(function (pair, i) {
        nodes.push(h("rect", {
          key: "dm" + index + "-" + i, x: pair[0] - 3, y: pair[1] - 3, width: 6, height: 6,
          "data-series": "denied", style: { fill: C.high }
        }));
      });
    });

    nodes.push(h("text", {
      key: "ylabel", x: 14, y: CHART.top + plotH / 2, textAnchor: "middle", fontSize: 11,
      transform: "rotate(-90 14 " + (CHART.top + plotH / 2) + ")",
      style: { fill: "currentColor" }
    }, "Connections per run"));
    nodes.push(h("text", {
      key: "xlabel", x: CHART.left + plotW / 2, y: CHART.height - 8, textAnchor: "middle",
      fontSize: 11, style: { fill: "currentColor" }
    }, "Run start, as recorded"));

    return h("svg", {
      viewBox: "0 0 " + CHART.width + " " + CHART.height, width: "100%",
      role: "img", "aria-labelledby": ids.title + " " + ids.desc,
      style: { display: "block", maxWidth: "100%", height: "auto", color: "inherit" }
    },
      h("title", { id: ids.title }, props.title),
      h("desc", { id: ids.desc }, props.desc),
      nodes);
  }

  function SeriesTable(props) {
    return h("details", null,
      h("summary", { style: Object.assign({}, S.small, { cursor: "pointer" }) },
        "The series as a table"),
      h(Table, {
        rows: props.points,
        columns: [
          { key: "run_id", label: "Run", render: function (p) { return h(Mono, null, p.run_id); } },
          { key: "started_at", label: "Run start", render: function (p) { return stamp(p.started_at); } },
          { key: "status", label: "Status", render: function (p) {
            return p.malformed ? "malformed record" : p.status || "unknown";
          } },
          { key: "ai", label: "AI traffic", render: function (p) {
            var kind = pointKind(p);
            return kind === "ok" || kind === "partial" ? count(p.ai_connections) : "no figure";
          } },
          { key: "other", label: "Other traffic", render: function (p) {
            var kind = pointKind(p);
            return kind === "ok" || kind === "partial" ?
              count(Math.max(0, p.connections - (p.ai_connections || 0))) : "no figure";
          } },
          { key: "denied", label: "Denied", render: function (p) {
            var kind = pointKind(p);
            return kind === "ok" || kind === "partial" ? count(p.denied) : "no figure";
          } }
        ]
      }));
  }

  function ConnectionsChart(props) {
    var idState = useState("hermes-snitchboard-chart-" + (++chartSeq));
    var base = idState[0];
    var ids = { hatch: base + "-hatch", title: base + "-title", desc: base + "-desc" };
    var series = props.series;
    var demo = series && typeof series.demo === "boolean" ? series.demo : props.demo;
    var points = series && Array.isArray(series.points) ? series.points : null;
    var selected = props.record && props.record.run_id;

    var content;
    if (props.seriesError) {
      content = h(Note, null, "The series could not be loaded: " + props.seriesError);
    } else if (!points) {
      content = h(Muted, null, "Loading the series.");
    } else if (!points.length) {
      content = h(Muted, null, "No runs are stored, so there is nothing to chart.");
    } else {
      var kinds = {};
      points.forEach(function (p) { kinds[pointKind(p)] = true; });
      var shown = points.some(function (p) { return p.run_id === selected; });
      var desc = "Stacked columns of AI and other traffic for each of the last " +
        points.length + " runs, with denied connections as a line." +
        (kinds.no_data ? " Runs without collected data are left as gaps." : "");
      content = [
        h("div", { key: "legend", style: S.row },
          h(LegendItem, { kind: "ai", hatch: ids.hatch, label: "AI traffic (hatched)" }),
          h(LegendItem, { kind: "other", label: "Other traffic (solid)" }),
          h(LegendItem, { kind: "denied", label: "Denied (dashed line, square markers)" }),
          kinds.no_data ? h(LegendItem, { kind: "no_data", label: "No data collected: a gap, not a zero" }) : null,
          kinds.malformed ? h(LegendItem, { kind: "malformed", label: "Malformed record" }) : null,
          kinds.partial ? h(LegendItem, { kind: "partial", label: "Partial run (dashed outline)" }) : null,
          shown ? h(LegendItem, { kind: "selected", label: "The run shown on this tab" }) : null),
        h(ChartSvg, {
          key: "svg", points: points, ids: ids, selected: selected,
          title: "Connections per run, last " + points.length + " runs", desc: desc
        }),
        h(Muted, { key: "caption" }, "One column per stored run, oldest on the left. " +
          "Hours with no run at all appear in the Coverage panel instead. Denied " +
          "connections are counted inside the columns as well as on the line."),
        h(SeriesTable, { key: "table", points: points })
      ];
    }
    return h(Panel, { id: "connections", title: "Connections", demo: demo }, content);
  }

  // --------------------------------------------------------- 11 events

  var CLIP = {
    display: "block", overflow: "hidden", textOverflow: "ellipsis",
    whiteSpace: "nowrap"
  };

  // Long values are cut to fit; the whole value stays available on hover.
  function Clip(props) {
    var value = props.value === null || props.value === undefined ? props.empty : String(props.value);
    return h("span", {
      className: "font-mono", title: value,
      style: Object.assign({}, CLIP, { maxWidth: props.width || "14rem" })
    }, value);
  }

  var STICKY_TH = Object.assign({}, S.th, {
    position: "sticky", top: 0, zIndex: 1,
    background: "var(--color-card, var(--color-background, Canvas))"
  });

  function plain(value) {
    return value === null || value === undefined ? "n/a" : String(value);
  }

  var EVENT_COLUMNS = [
    { key: "rank", label: "#", render: function (r, i) { return String(i + 1); } },
    { key: "ts", label: "Time", render: function (r) {
      return h("span", { style: { whiteSpace: "nowrap" } }, stamp(r.ts));
    } },
    { key: "action", label: "Action", render: function (r) {
      return r.action === "deny" ? h(Pill, { level: "high" }, "deny") : String(r.action);
    } },
    { key: "src", label: "Source", render: function (r) { return h(Clip, { value: r.src, empty: "n/a", width: "9rem" }); } },
    { key: "dst", label: "Destination", render: function (r) { return h(Clip, { value: r.dst, empty: "n/a" }); } },
    { key: "dport", label: "Port", render: function (r) { return plain(r.dport); } },
    { key: "proto", label: "Protocol", render: function (r) { return plain(r.proto); } },
    { key: "uid", label: "UID", render: function (r) { return plain(r.uid); } },
    { key: "pid", label: "PID", render: function (r) { return plain(r.pid); } },
    { key: "process", label: "Process", render: function (r) {
      return h(Clip, { value: r.process, empty: "unattributed", width: "16rem" });
    } },
    { key: "activity", label: "Activity", render: function (r) {
      return h("span", { style: { display: "block", minWidth: "10rem", lineHeight: 1.4 } }, r.activity);
    } },
    { key: "is_ai", label: "AI", render: function (r) {
      return r.is_ai ? h("span", { style: { fontWeight: 700 } }, "AI") : h("span", { style: S.small }, "no");
    } },
    { key: "severity", label: "Severity", render: function (r) { return h(Pill, { level: r.severity }, r.severity); } }
  ];

  function Events(props) {
    var record = props.record;
    var rows = record.rows;
    var cap = capOf(props.caps, "rows");
    var content;
    if (!Array.isArray(rows)) {
      content = h(Muted, null, gapText(record));
    } else if (!rows.length) {
      content = h(Muted, null, "No connections were recorded in this run.");
    } else {
      content = [
        h(Muted, { key: "caption" }, rows.length + " of at most " + cap +
          " rows held, in the order the record ranks them. Hover over a shortened " +
          "value to read it in full."),
        // The table scrolls inside its own box, so the page never does.
        h("div", {
          key: "table",
          style: {
            overflow: "auto", maxHeight: "36rem", maxWidth: "100%",
            border: "1px solid " + C.border, borderRadius: "var(--radius, 0.5rem)"
          }
        },
          h("table", { style: S.table },
            h("thead", null, h("tr", null, EVENT_COLUMNS.map(function (col) {
              return h("th", { key: col.key, style: STICKY_TH, scope: "col" }, col.label);
            }))),
            h("tbody", null, rows.map(function (row, index) {
              return h("tr", { key: index }, EVENT_COLUMNS.map(function (col) {
                return h("td", { key: col.key, style: S.td }, col.render(row, index));
              }));
            }))))
      ];
    }
    return h(Panel, { id: "events", title: "Events", demo: props.demo }, content);
  }

  // ----------------------------------------------------- 12 aggregates

  var AGGREGATE_TABLES = [
    ["hosts", "Destinations", "hosts"], ["procs", "Processes", "aggregates"],
    ["users", "Accounts", "aggregates"], ["ports", "Ports", "aggregates"],
    ["addrs", "Addresses", "addrs"]
  ];
  var AT_CAP = "Less frequent entries are not held.";

  function Tally(props) {
    var items = props.items;
    var body;
    if (!Array.isArray(items)) {
      body = h(Muted, null, SECTION_ABSENT);
    } else if (!items.length) {
      body = h(Muted, null, "None recorded.");
    } else {
      body = [
        h(Muted, { key: "caption" }, items.length + " of at most " + props.cap + " entries." +
          (items.length >= props.cap ? " " + AT_CAP : "")),
        h("table", { key: "table", style: Object.assign({}, S.table, { tableLayout: "fixed" }) },
          h("thead", null, h("tr", null,
            h("th", { style: S.th, scope: "col" }, props.label),
            h("th", { style: Object.assign({}, S.th, { textAlign: "right", width: "5rem" }), scope: "col" }, "Hits"))),
          h("tbody", null, items.map(function (item, index) {
            return h("tr", { key: index },
              h("td", { style: S.td }, h(Mono, null, item && item.what)),
              h("td", { style: Object.assign({}, S.td, { textAlign: "right", fontVariantNumeric: "tabular-nums" }) },
                count(item && item.hits)));
          })))
      ];
    }
    return h("div", { style: { display: "flex", flexDirection: "column", gap: sp(2), minWidth: 0 } },
      h("h4", { style: { margin: 0, fontSize: "0.9375rem", fontWeight: 600 } }, props.label),
      body);
  }

  function Aggregates(props) {
    var record = props.record;
    var agg = record.aggregates;
    var content;
    if (!agg || typeof agg !== "object") {
      content = h(Muted, null, gapText(record));
    } else {
      content = h("div", {
        style: {
          display: "grid", gap: sp(4),
          gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 16rem), 1fr))"
        }
      }, AGGREGATE_TABLES.map(function (spec) {
        return h(Tally, {
          key: spec[0], label: spec[1], items: agg[spec[0]], cap: capOf(props.caps, spec[2])
        });
      }));
    }
    return h(Panel, { id: "aggregates", title: "Aggregates", demo: props.demo }, content);
  }

  // ------------------------------------------------- Tier C helpers

  var NOT_REPORTED = "not reported";

  // Byte counts as measured, in binary units. Nothing is rounded up to a
  // figure the record does not hold; the exact count is kept for the hover.
  function bytes(value) {
    if (typeof value !== "number" || value < 0) return "n/a";
    var units = ["B", "KiB", "MiB", "GiB"];
    var scaled = value;
    var unit = 0;
    while (scaled >= 1024 && unit < units.length - 1) {
      scaled = scaled / 1024;
      unit += 1;
    }
    var digits = unit === 0 ? 0 : 1;
    return scaled.toLocaleString("en-GB", {
      minimumFractionDigits: digits, maximumFractionDigits: digits
    }) + " " + units[unit];
  }

  function exactBytes(value) {
    return typeof value === "number" ? count(value) + " bytes" : "";
  }

  function uptime(seconds) {
    if (typeof seconds !== "number" || seconds < 0) return "n/a";
    var days = Math.floor(seconds / 86400);
    var hours = Math.floor((seconds % 86400) / 3600);
    var minutes = Math.floor((seconds % 3600) / 60);
    if (days > 0) return days + " d " + hours + " h";
    if (hours > 0) return hours + " h " + minutes + " min";
    if (minutes > 0) return minutes + " min " + Math.floor(seconds % 60) + " s";
    return Math.floor(seconds) + " s";
  }

  function reported(value) {
    if (value === null || value === undefined || value === "") return NOT_REPORTED;
    return value;
  }

  function yesNo(value) {
    return value === true ? "yes" : value === false ? "no" : NOT_REPORTED;
  }

  // Aggregates are absent from a trimmed record, which is not the same as an
  // aggregate list that is present and empty.
  function aggregatesOf(record) {
    var agg = record && record.aggregates;
    return agg && typeof agg === "object" ? agg : null;
  }

  // ------------------------------------------------------- 13 volume

  function Volume(props) {
    var record = props.record;
    var volume = record.volume;
    var body;
    if (record.trimmed || !volume || typeof volume !== "object") {
      body = h(Muted, null, gapText(props.record));
    } else if (volume.available !== true) {
      body = [
        h(Note, { key: "unavailable" }, "Volume is unavailable for this run, so no " +
          "byte figure is shown and none has been estimated."),
        volume.note ? h(Muted, { key: "note" }, volume.note) : null
      ];
    } else {
      var rows = Array.isArray(volume.rows) ? volume.rows : [];
      body = [
        volume.note ? h(Muted, { key: "note" }, volume.note) : null,
        rows.length ? h(Table, {
          key: "table",
          rows: rows,
          columns: [
            { key: "process", label: "Process", render: function (r) { return h(Mono, null, r.process || "unattributed"); } },
            { key: "destination", label: "Destination", render: function (r) { return h(Mono, null, r.destination); } },
            { key: "sent_bytes", label: "Sent", render: function (r) { return h("span", { title: exactBytes(r.sent_bytes), style: { whiteSpace: "nowrap" } }, bytes(r.sent_bytes)); } },
            { key: "recv_bytes", label: "Received", render: function (r) { return h("span", { title: exactBytes(r.recv_bytes), style: { whiteSpace: "nowrap" } }, bytes(r.recv_bytes)); } },
            { key: "flows", label: "Flows", render: function (r) { return count(r.flows); } },
            { key: "assessment", label: "Assessment", render: function (r) { return h("span", { style: { lineHeight: 1.5 } }, r.assessment); } }
          ]
        }) : h(Muted, { key: "empty" }, "Volume was measured, but no flow in this " +
          "window could be joined to a process."),
        rows.length ? h(Muted, { key: "caption" }, rows.length + " flow row(s), ranked " +
          "by total bytes. A record keeps at most " + capOf(props.caps, "volume_rows") + " of them.") : null
      ];
    }
    return h(Panel, { id: "volume", title: "Volume", demo: props.demo }, body);
  }

  // ------------------------------------------------- 14 daemon state

  var NODE_FIELDS = [
    ["status", "Status"], ["hostname", "Host name"], ["addr", "Address"],
    ["daemon_version", "Daemon version"], ["version", "Node version"],
    ["daemon_uptime", "Node uptime"], ["daemon_rules", "Rules loaded"],
    ["cons", "Connections seen"], ["cons_dropped", "Connections dropped"],
    ["last_connection", "Last connection"]
  ];

  var DAEMON_TOTALS = [
    ["daemon_uptime", "Daemon uptime"], ["total_connections", "Total connections"],
    ["dropped", "Dropped"], ["rules", "Rules"]
  ];

  function nodeValue(name, value) {
    if (name === "daemon_uptime") return uptime(value);
    if (name === "last_connection") return value ? stamp(value) : NOT_REPORTED;
    if (typeof value === "number") return count(value);
    if (name === "hostname" || name === "addr") {
      return value ? h(Mono, null, value) : NOT_REPORTED;
    }
    return reported(value);
  }

  function Facts(props) {
    return h("dl", {
      style: {
        display: "grid", margin: 0, gap: sp(2) + " " + sp(4),
        gridTemplateColumns: "repeat(auto-fill, minmax(12rem, 1fr))"
      }
    }, props.items.map(function (item) {
      return h("div", { key: item[0], style: { display: "grid", gap: sp(0.5), minWidth: 0 } },
        h("dt", { style: S.small }, item[1]),
        h("dd", { style: { margin: 0, overflowWrap: "anywhere" } }, item[2]));
    }));
  }

  function DaemonState(props) {
    var agg = aggregatesOf(props.record);
    var body;
    if (props.record.trimmed || !agg) {
      body = h(Muted, null, gapText(props.record));
    } else {
      var node = agg.node && typeof agg.node === "object" ? agg.node : null;
      body = [
        h(Muted, { key: "intro" }, "As the collector reported the firewall daemon " +
          "when this run was collected. These values describe that moment only."),
        h(Facts, {
          key: "totals",
          items: DAEMON_TOTALS.map(function (pair) {
            var value = agg[pair[0]];
            return [pair[0], pair[1], pair[0] === "daemon_uptime" ? uptime(value) : count(value)];
          })
        }),
        node ? h(Facts, {
          key: "node",
          items: NODE_FIELDS.map(function (pair) {
            return [pair[0], pair[1], nodeValue(pair[0], node[pair[0]])];
          })
        }) : h(Muted, { key: "no-node" }, "The collector reported no node row for this run.")
      ];
    }
    return h(Panel, { id: "daemon", title: "Daemon state", demo: props.demo }, body);
  }

  // ------------------------------------------------------- 15 rules

  function RulesInForce(props) {
    var agg = aggregatesOf(props.record);
    var rules = agg && Array.isArray(agg.rules_detail) ? agg.rules_detail : null;
    var body;
    if (props.record.trimmed || !rules) {
      body = h(Muted, null, gapText(props.record));
    } else if (!rules.length) {
      body = h(Muted, null, "No rules were reported at collection time.");
    } else {
      body = h(Table, {
        rows: rules,
        columns: [
          { key: "name", label: "Name", render: function (r) { return h(Mono, null, r.name); } },
          { key: "enabled", label: "Enabled", render: function (r) { return yesNo(r.enabled); } },
          { key: "precedence", label: "Precedence", render: function (r) { return yesNo(r.precedence); } },
          { key: "action", label: "Action", render: function (r) {
            return r.action === "deny" ? h(Pill, { level: "high" }, "deny") : reported(r.action);
          } },
          { key: "duration", label: "Duration", render: function (r) { return reported(r.duration); } },
          { key: "operator", label: "Operator", render: function (r) {
            return h("span", null, reported(r.operator_type),
              h("div", { style: S.small }, reported(r.operator_operand)));
          } },
          { key: "operator_data", label: "Matches", render: function (r) {
            return h("span", { className: "font-mono", style: { overflowWrap: "anywhere" } },
              reported(r.operator_data));
          } },
          { key: "created", label: "Created", render: function (r) { return r.created ? stamp(r.created) : NOT_REPORTED; } }
        ]
      });
    }
    return h(Panel, { id: "rules", title: "Rules in force", demo: props.demo }, body);
  }

  // ----------------------------------------------------- 16 sockets

  function Sockets(props) {
    var agg = aggregatesOf(props.record);
    var sockets = agg && Array.isArray(agg.sockets) ? agg.sockets : null;
    var body;
    if (props.record.trimmed || !sockets) {
      body = h(Muted, null, gapText(props.record));
    } else if (!sockets.length) {
      body = h(Muted, null, "No sockets were recorded. That can mean socket " +
        "monitoring is disabled on this host, not that no socket was open.");
    } else {
      body = h(Table, {
        rows: sockets,
        columns: [
          { key: "what", label: "Socket", render: function (r) { return h(Mono, null, r.what); } },
          { key: "hits", label: "Hits", render: function (r) { return count(r.hits); } }
        ]
      });
    }
    return h(Panel, { id: "sockets", title: "Sockets", demo: props.demo }, body);
  }

  // ------------------------------------------------------ 17 export

  var CSV_ROW_FIELDS = ["ts", "action", "src", "dst", "dport", "proto", "uid", "pid",
    "process", "activity", "is_ai", "severity"];
  var CSV_DETECTION_FIELDS = ["severity", "confidence", "title", "technique_id", "tactic_id"];

  // RFC 4180 quoting, after a leading quote mark has neutralised any cell a
  // spreadsheet would otherwise evaluate as a formula.
  function csvCell(value) {
    var text = value === null || value === undefined ? "" : String(value);
    if (/^[=+\-@\t\r]/.test(text)) text = "'" + text;
    if (/[",\r\n]/.test(text)) text = "\"" + text.replace(/"/g, "\"\"") + "\"";
    return text;
  }

  function csvLine(cells) {
    return cells.map(csvCell).join(",");
  }

  function csvForRecord(record) {
    var lines;
    if (record && !record.trimmed && Array.isArray(record.rows)) {
      lines = [csvLine(CSV_ROW_FIELDS)].concat(record.rows.map(function (row) {
        return csvLine(CSV_ROW_FIELDS.map(function (name) { return row[name]; }));
      }));
    } else {
      var detections = record && Array.isArray(record.detections) ? record.detections : [];
      lines = [csvLine(CSV_DETECTION_FIELDS)].concat(detections.map(function (d) {
        var a = d.attack || {};
        return csvLine([d.severity, d.confidence, d.title, a.technique_id, a.tactic_id]);
      }));
    }
    return lines.join("\r\n") + "\r\n";
  }

  function ExportButton(props) {
    var record = props.record;
    var failureState = useState(null), failure = failureState[0], setFailure = failureState[1];

    function save() {
      setFailure(null);
      var url = null;
      try {
        var blob = new Blob([csvForRecord(record)], { type: "text/csv;charset=utf-8" });
        url = URL.createObjectURL(blob);
        var anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = "hermes-snitchboard-" + record.run_id + "-" +
          (props.revealed ? "revealed" : "masked") + ".csv";
        anchor.style.display = "none";
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
      } catch (e) {
        setFailure(String((e && e.message) || e));
      }
      if (url) {
        window.setTimeout(function () { URL.revokeObjectURL(url); }, 0);
      }
    }

    return h("span", { style: S.row },
      h(Button, { variant: "outline", size: "sm", disabled: !record, onClick: save },
        "Export CSV"),
      record ? h("span", { style: S.small }, (record.trimmed ?
        "Exports this run's shortened findings" : "Exports this run's event rows") +
        (props.revealed ? ", with values revealed exactly as loaded." :
          ", masked exactly as loaded.")) : null,
      failure ? h("span", { style: { color: C.high } }, "Export failed: " + failure) : null);
  }

  // ---------------------------------------------------- 8 integrity

  function HashRow(props) {
    return h("div", { style: { display: "grid", gap: sp(0.5) } },
      h("span", { style: S.small }, props.label),
      h(Mono, null, props.value || "absent"));
  }

  function VerifyResult(props) {
    var v = props.result;
    if (!v) return null;
    var colour = v.intact === true ? C.good : v.intact === false ? C.high : C.medium;
    var heading = v.intact === true ? "Chain intact" :
      v.intact === false ? "Chain broken" : "No verdict";
    return h("div", { style: S.stack },
      h("div", { style: S.row }, h(Pill, { level: v.intact === true ? "good" : v.intact === false ? "high" : "medium" }, heading),
        h(DemoBadge, { demo: v.demo })),
      h("p", { style: Object.assign({}, S.para, { color: colour }) }, v.summary),
      v.first_break ? h(Note, null, "First break at position " + v.first_break.position +
        ", run " + v.first_break.run_id + ": " + v.first_break.note) : null,
      v.breaks && v.breaks.length > 1 ? h(Table, {
        rows: v.breaks,
        columns: [
          { key: "position", label: "Position" },
          { key: "run_id", label: "Run", render: function (r) { return h(Mono, null, r.run_id); } },
          { key: "note", label: "Problem" }
        ]
      }) : null,
      v.breaks_total > (v.breaks || []).length ? h(Muted, null, "Showing " +
        v.breaks.length + " of " + v.breaks_total + " broken links.") : null,
      v.trimmed_notice ? h(Note, null, v.sealed_links + " link(s) rest on trimmed records. " +
        v.trimmed_notice) : null,
      v.complete ? h(Muted, null, v.checked + " run(s) checked, " +
        v.malformed_records + " malformed.") : null);
  }

  function Integrity(props) {
    var record = props.record;
    var block = record.integrity || {};
    return h(Panel, { id: "integrity", title: "Integrity", demo: props.demo },
      h("div", { style: { display: "grid", gap: sp(3) } },
        h(HashRow, { label: "Chain position (run index)", value: String(block.run_index) }),
        h(HashRow, { label: "Content digest (SHA-256)", value: block.content_sha256 }),
        record.trimmed ? h(HashRow, {
          label: "Sealed digest of the original full record", value: block.sealed_sha256
        }) : null,
        h(HashRow, { label: "Previous link digest", value: block.prev_sha256 })),
      record.trimmed ? h(Note, null, "This trimmed record's summary is not covered by " +
        "the chain. The chain still fixes its position and the digest its full form " +
        "held, but an edit to this summary made together with a recomputed content " +
        "digest would go undetected. Treat what is shown for this run as a derived " +
        "aid, not as evidence.") : null,
      h(Muted, null, "The chain makes alteration of stored records detectable. It does " +
        "not prove that the records match what the network did, and anyone able to " +
        "rewrite every record could recompute the chain."),
      h("div", { style: S.row },
        h(Button, { variant: "outline", size: "sm", onClick: props.onVerify, disabled: props.verifying },
          props.verifying ? "Verifying" : "Verify chain"),
        props.verifyError ? h("span", { style: { color: C.high } }, props.verifyError) : null),
      h(VerifyResult, { result: props.verifyResult }));
  }

  // ------------------------------------------------------ 9 caveats

  var CAVEATS = [
    ["Remote content stays encrypted",
      "Hermes Snitchboard sees that a connection was made, where it went and which process " +
      "made it. What travelled inside an encrypted session is not visible here, and " +
      "no attempt is made to read it."],
    ["Local agent content is obtainable",
      "Content an agent sends is encrypted on the wire, yet the same text usually " +
      "exists in plain form on this machine first, in prompts, logs, caches and " +
      "session stores. Protecting those files matters as much as watching the network."],
    ["More metadata exists than is collected",
      "The firewall holds more detail than each record keeps. Records are a capped, " +
      "deliberate subset, so the absence of something from a record does not prove " +
      "that it did not occur."],
    ["Volume comes from connection tracking",
      "Byte counts, where present, are measured by the kernel's connection tracking " +
      "and joined to the owning process. Nothing is estimated, and a flow that began " +
      "before the window may be reported as unpaired."],
    ["Collection is hourly",
      "Each run summarises a one-hour window. Timing inside the hour is approximate, " +
      "and a short burst near a window boundary can fall either side of it."],
    ["Collection follows the desktop session",
      "The reference collector runs within the owner's session. While that session " +
      "is closed no run is collected, and the hour appears as a gap rather than as a " +
      "quiet hour."],
    ["Container attribution is unverified",
      "Traffic from containers and sandboxes is attributed to whichever host process " +
      "the firewall reports, often the container runtime. That attribution has not " +
      "been checked against the process inside the container."],
    ["Detection confidence is not certainty",
      "Severity and confidence come from fixed rules applied to metadata. A " +
      "high-confidence finding is a strong reason to look, not a conclusion, and a " +
      "run without findings is no guarantee that nothing happened."]
  ];

  function Caveats() {
    return h(Panel, { id: "caveats", title: "Caveats" },
      h("ol", { style: { margin: 0, paddingLeft: sp(5), display: "grid", gap: sp(3) } },
        CAVEATS.map(function (pair) {
          return h("li", { key: pair[0] },
            h("div", { style: { fontWeight: 600 } }, pair[0]),
            h("p", { style: S.para }, pair[1]));
        })));
  }

  // ----------------------------------------------------------- data

  function fetchJSON(path) {
    if (typeof SDK.fetchJSON === "function") return SDK.fetchJSON(API + path);
    return Promise.reject(new Error("the dashboard SDK offers no fetch helper"));
  }

  function message(error) {
    return String((error && error.message) || error || "request failed");
  }

  function recordPath(runId, reveal) {
    var base = runId ? "/runs/" + encodeURIComponent(runId) : "/runs/latest";
    return reveal === null ? base : base + "?reveal=" + (reveal ? "true" : "false");
  }

  // --------------------------------------------------------- the tab

  function HermesSnitchboardTab() {
    var healthState = useState(null), health = healthState[0], setHealth = healthState[1];
    var settingsState = useState(null), settings = settingsState[0], setSettings = settingsState[1];
    var runsState = useState({ items: [], total: 0 }), runs = runsState[0], setRuns = runsState[1];
    var selectedState = useState(null), selected = selectedState[0], setSelected = selectedState[1];
    // null leaves masking to the server's setting until the viewer chooses.
    var revealState = useState(null), reveal = revealState[0], setReveal = revealState[1];
    var payloadState = useState(null), payload = payloadState[0], setPayload = payloadState[1];
    var errorState = useState(null), error = errorState[0], setError = errorState[1];
    var loadingState = useState(true), loading = loadingState[0], setLoading = loadingState[1];
    var moreState = useState(false), loadingMore = moreState[0], setLoadingMore = moreState[1];
    var verifyState = useState(null), verifyResult = verifyState[0], setVerifyResult = verifyState[1];
    var verifyingState = useState(false), verifying = verifyingState[0], setVerifying = verifyingState[1];
    var verifyErrorState = useState(null), verifyError = verifyErrorState[0], setVerifyError = verifyErrorState[1];
    var capsState = useState(null), caps = capsState[0], setCaps = capsState[1];
    var seriesState = useState(null), series = seriesState[0], setSeries = seriesState[1];
    var seriesErrorState = useState(null), seriesError = seriesErrorState[0], setSeriesError = seriesErrorState[1];

    // The first load fetches summaries, the compact chart series and one
    // record, never the history (NFR5).
    useEffect(function () {
      var live = true;
      Promise.all([
        fetchJSON("/health"), fetchJSON("/settings"),
        fetchJSON("/runs?limit=" + RUNS_PAGE + "&offset=0")
      ]).then(function (results) {
        if (!live) return;
        setHealth(results[0]);
        setSettings(results[1].settings);
        setCaps(results[1].caps || null);
        setRuns({ items: results[2].runs, total: results[2].total });
      }).catch(function (e) { if (live) setError(message(e)); });
      // The chart has its own request, so a failure here leaves the other
      // panels untouched.
      fetchJSON("/series?n=" + SERIES_RUNS).then(function (body) {
        if (live) setSeries(body);
      }).catch(function (e) { if (live) setSeriesError(message(e)); });
      return function () { live = false; };
    }, []);

    // The runs directory path in the header is masked and revealed together
    // with the record values. The server refuses reveal when it is disabled,
    // so the choice is sent only where reveal is allowed.
    useEffect(function () {
      if (reveal === null || !settings || !settings.allow_reveal) return undefined;
      var live = true;
      fetchJSON("/health?reveal=" + (reveal ? "true" : "false")).then(function (body) {
        if (live) setHealth(body);
      }).catch(function (e) { if (live) setError(message(e)); });
      return function () { live = false; };
    }, [reveal, settings]);

    var loadRecord = useCallback(function (runId, reveal) {
      setLoading(true);
      setError(null);
      return fetchJSON(recordPath(runId, reveal)).then(function (body) {
        setPayload(body);
      }).catch(function (e) {
        setPayload(null);
        setError(message(e));
      }).then(function () { setLoading(false); });
    }, []);

    useEffect(function () { loadRecord(selected, reveal); }, [selected, reveal, loadRecord]);

    function loadMore() {
      setLoadingMore(true);
      fetchJSON("/runs?limit=" + RUNS_PAGE + "&offset=" + runs.items.length).then(function (body) {
        setRuns({ items: runs.items.concat(body.runs), total: body.total });
      }).catch(function (e) { setError(message(e)); })
        .then(function () { setLoadingMore(false); });
    }

    function toggleReveal() {
      setReveal(!(payload && payload.revealed));
    }

    function verify() {
      setVerifying(true);
      setVerifyError(null);
      fetchJSON("/verify").then(setVerifyResult)
        .catch(function (e) { setVerifyError(message(e)); })
        .then(function () { setVerifying(false); });
    }

    var demo = !!(payload ? payload.demo : health && health.demo);
    var record = payload && !payload.malformed ? payload.record : null;

    var body;
    if (loading && !payload) {
      body = h(Muted, null, "Loading the most recent run.");
    } else if (payload && payload.malformed) {
      body = h(Panel, { id: "malformed", title: "Malformed record", demo: demo },
        h(Note, null, "Run " + payload.run_id + " does not satisfy the record schema, " +
          "so it is reported here instead of being drawn. Other runs remain available " +
          "in the selector."),
        h("ul", { style: { margin: 0, paddingLeft: sp(5) } },
          payload.problems.map(function (p, i) { return h("li", { key: i }, h(Mono, null, p)); })),
        payload.problem_count > payload.problems.length ? h(Muted, null,
          (payload.problem_count - payload.problems.length) + " further problem(s) not shown.") : null);
    } else if (record) {
      var panels = [
        ["Summary", Summary], ["Coverage", Coverage], ["Findings", Findings],
        ["Beacons", Beacons], ["Novel destinations", Novel], ["Agents", Agents],
        ["Connections", ConnectionsChart], ["Events", Events], ["Aggregates", Aggregates],
        ["Volume", Volume], ["Daemon state", DaemonState], ["Rules in force", RulesInForce],
        ["Sockets", Sockets], ["Integrity", Integrity]
      ];
      var panelProps = {
        record: record, demo: demo, caps: caps, series: series, seriesError: seriesError,
        onVerify: verify, verifying: verifying, verifyResult: verifyResult,
        verifyError: verifyError
      };
      body = panels.map(function (pair) {
        return h(PanelGuard, { key: pair[0], title: pair[0] }, h(pair[1], panelProps));
      });
    } else {
      body = h(Note, null, error ? "The run could not be loaded: " + error :
        "No run record is available. Absence of records is absence of collection, " +
        "not evidence that nothing happened.");
    }

    return h("div", {
      "data-snitchboard": "tab",
      style: { display: "flex", flexDirection: "column", gap: sp(4), minWidth: 0 }
    },
      h(PanelGuard, { title: "Hermes Snitchboard" },
        h(Header, {
          health: health, settings: settings, runs: runs, payload: payload,
          selected: selected, onSelect: setSelected, onMore: loadMore,
          loadingMore: loadingMore, onToggleReveal: toggleReveal
        })),
      error && payload ? h(Note, null, "Request failed: " + error) : null,
      body,
      h(PanelGuard, { title: "Caveats" }, h(Caveats)));
  }

  // The test suite sets this hook before loading the file so that panels can
  // be rendered one by one. The dashboard never sets it.
  var testHook = window.__HERMES_SNITCHBOARD_TEST__;
  if (testHook && typeof testHook === "object") {
    testHook.components = {
      Header: Header, Summary: Summary, Coverage: Coverage, Findings: Findings,
      Beacons: Beacons, Novel: Novel, Agents: Agents,
      ConnectionsChart: ConnectionsChart, Events: Events, Aggregates: Aggregates,
      Volume: Volume, DaemonState: DaemonState, RulesInForce: RulesInForce,
      Sockets: Sockets, ExportButton: ExportButton,
      Integrity: Integrity, Caveats: Caveats, HermesSnitchboardTab: HermesSnitchboardTab
    };
    testHook.CAPS_FALLBACK = CAPS_FALLBACK;
    testHook.csvForRecord = csvForRecord;
  }

  registry.register(PLUGIN, HermesSnitchboardTab);
})();
