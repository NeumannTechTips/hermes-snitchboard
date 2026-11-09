/*
 * Snitchboard dashboard tab, Tier A (HSB-PRD-001 sections 7.9 and 7.10).
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
  var TRIMMED_GAP = "Not retained: trimmed records keep only the summary, the " +
    "shortened findings and the destination list.";

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
          h(CardTitle, null, "Snitchboard"),
          h("div", { style: S.row }, modeBadge,
            h(Badge, { variant: "outline" }, revealed ? "Values revealed" : "Values masked")))),
      h(CardContent, null,
        h("div", { style: S.stack },
          h("div", { style: S.row }, selector, more, toggle),
          h("div", { style: S.row },
            h(Muted, null, "Last collection: " + lastCollected),
            record ? h(Muted, null, "Showing " + record.run_id + ", window " +
              stamp(record.window_start) + " to " + stamp(record.window_end)) : null),
          demo ? h(Note, null, "No run records were found, so the tab is showing " +
            "synthetic demonstration data. Every address and name in it comes from " +
            "the ranges reserved for documentation.") : null,
          health.runs_dir && health.runs_dir.status !== "ok" ? h(Muted, null,
            "Runs directory (" + health.runs_dir.location + "): " +
            health.runs_dir.status.replace(/_/g, " ") + ".") : null,
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
      "Snitchboard sees that a connection was made, where it went and which process " +
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

  function SnitchboardTab() {
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

    // The first load fetches summaries and one record, never the history (NFR5).
    useEffect(function () {
      var live = true;
      Promise.all([
        fetchJSON("/health"), fetchJSON("/settings"),
        fetchJSON("/runs?limit=" + RUNS_PAGE + "&offset=0")
      ]).then(function (results) {
        if (!live) return;
        setHealth(results[0]);
        setSettings(results[1].settings);
        setRuns({ items: results[2].runs, total: results[2].total });
      }).catch(function (e) { if (live) setError(message(e)); });
      return function () { live = false; };
    }, []);

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
        ["Beacons", Beacons], ["Novel destinations", Novel], ["Agents", Agents]
      ];
      body = panels.map(function (pair) {
        return h(PanelGuard, { key: pair[0], title: pair[0] },
          h(pair[1], { record: record, demo: demo }));
      }).concat([h(PanelGuard, { key: "Integrity", title: "Integrity" },
        h(Integrity, {
          record: record, demo: demo, onVerify: verify, verifying: verifying,
          verifyResult: verifyResult, verifyError: verifyError
        }))]);
    } else {
      body = h(Note, null, error ? "The run could not be loaded: " + error :
        "No run record is available. Absence of records is absence of collection, " +
        "not evidence that nothing happened.");
    }

    return h("div", {
      "data-snitchboard": "tab",
      style: { display: "flex", flexDirection: "column", gap: sp(4), minWidth: 0 }
    },
      h(PanelGuard, { title: "Snitchboard" },
        h(Header, {
          health: health, settings: settings, runs: runs, payload: payload,
          selected: selected, onSelect: setSelected, onMore: loadMore,
          loadingMore: loadingMore, onToggleReveal: toggleReveal
        })),
      error && payload ? h(Note, null, "Request failed: " + error) : null,
      body,
      h(PanelGuard, { title: "Caveats" }, h(Caveats)));
  }

  registry.register(PLUGIN, SnitchboardTab);
})();
