/*
 * Render smoke test for the dashboard bundle, driven by test_dashboard_render.py.
 *
 * A minimal stand-in for React builds plain element objects, so each panel
 * can be rendered against the synthetic fixtures without a browser or any
 * package. Hooks are inert: state keeps its initial value and effects do not
 * run. Exits with status 1 and a message on the first failure.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const repo = path.resolve(__dirname, "..");
const runsDir = path.join(repo, "fixtures", "runs");

function Component(props) { this.props = props; }
Component.prototype.render = function () { return null; };

const React = {
  Component: Component,
  createElement: function (type, props) {
    const children = Array.prototype.slice.call(arguments, 2);
    const merged = Object.assign({}, props || {});
    if (children.length === 1) merged.children = children[0];
    else if (children.length > 1) merged.children = children;
    return { type: type, props: merged };
  }
};
const hooks = {
  useState: function (initial) {
    return [typeof initial === "function" ? initial() : initial, function () {}];
  },
  useEffect: function () {},
  useCallback: function (fn) { return fn; }
};

let registered = null;
const window = {
  __HERMES_PLUGIN_SDK__: {
    React: React, hooks: hooks, components: {},
    fetchJSON: function () { return new Promise(function () {}); }
  },
  __HERMES_PLUGINS__: { register: function (name, component) { registered = [name, component]; } },
  __HERMES_SNITCHBOARD_TEST__: {}
};
window.window = window;
vm.runInNewContext(fs.readFileSync(path.join(repo, "dashboard", "dist", "index.js"), "utf8"),
  window, { filename: "index.js" });

const parts = window.__HERMES_SNITCHBOARD_TEST__.components;

function fail(message) {
  process.stderr.write(message + "\n");
  process.exit(1);
}

if (!registered || registered[0] !== "hermes-snitchboard") fail("the tab was not registered");
if (!parts) fail("the test hook received no components");

// Expand every component into host elements, collecting text and elements.
function render(node, out) {
  if (node === null || node === undefined || typeof node === "boolean") return out;
  if (typeof node === "string" || typeof node === "number") {
    out.text.push(String(node));
    return out;
  }
  if (Array.isArray(node)) {
    node.forEach(function (child) { render(child, out); });
    return out;
  }
  const type = node.type;
  const props = node.props || {};
  if (Object.prototype.hasOwnProperty.call(props, "dangerouslySetInnerHTML")) {
    fail("an element carries dangerouslySetInnerHTML");
  }
  if (typeof type === "function") {
    if (type.prototype && typeof type.prototype.render === "function" &&
        type.prototype.render !== Component.prototype.render) {
      const instance = new type(props);
      instance.props = props;
      return render(instance.render(), out);
    }
    return render(type(props), out);
  }
  out.elements.push(node);
  return render(props.children, out);
}

function draw(component, props) {
  return render(React.createElement(component, props), { text: [], elements: [] });
}

function load(runId) {
  return JSON.parse(fs.readFileSync(path.join(runsDir, runId + ".json"), "utf8"));
}

const files = fs.readdirSync(runsDir).filter(function (n) { return n.endsWith(".json"); }).sort();
const records = files.map(function (n) { return load(n.slice(0, -5)); });
const newest = records[records.length - 1];
const trimmed = records.find(function (r) { return r.trimmed && r.status === "ok"; });
const noData = records.find(function (r) { return r.status === "no_data"; });
if (newest.trimmed || !trimmed || !noData) fail("the fixtures lack a full, trimmed or no_data run");

const points = records.map(function (r) {
  return {
    run_id: r.run_id, malformed: false, started_at: r.started_at, status: r.status,
    connections: r.totals.connections, ai_connections: r.totals.ai_connections,
    denied: r.totals.denied
  };
}).slice(-24);
const seriesOk = { mode: "demo", demo: true, n: 24, points: points };
const withMalformed = {
  mode: "demo", demo: true, n: 24,
  points: points.slice(0, 5).concat([{ run_id: "run-20261101T120002Z", malformed: true }],
    points.slice(5))
};
const emptySeries = { mode: "demo", demo: true, n: 24, points: [] };
const caps = { rows: 120, volume_rows: 45, hosts: 20, addrs: 15, novel: 15, beacons: 16, aggregates: 20 };

const panelNames = ["Summary", "Coverage", "Findings", "Beacons", "Novel", "Agents",
  "ConnectionsChart", "Events", "Aggregates", "Volume", "DaemonState", "RulesInForce",
  "Sockets", "Integrity"];

[newest, trimmed, noData].forEach(function (record) {
  [seriesOk, withMalformed, emptySeries, null].forEach(function (series) {
    panelNames.forEach(function (name) {
      try {
        draw(parts[name], {
          record: record, demo: true, caps: caps, series: series, seriesError: null,
          onVerify: function () {}, verifying: false, verifyResult: null, verifyError: null
        });
      } catch (error) {
        fail(name + " failed for " + record.run_id + ": " + (error && error.stack || error));
      }
    });
  });
});

// A trimmed record says what it lacks rather than drawing empty tables.
["Events", "Aggregates", "Volume", "DaemonState", "RulesInForce", "Sockets"].forEach(function (name) {
  [trimmed, noData].forEach(function (record) {
    const out = draw(parts[name], { record: record, demo: true, caps: caps });
    if (!out.text.join(" ").includes("Not held in this record")) {
      fail(name + " does not say the section is not held for " + record.run_id);
    }
    if (out.elements.some(function (e) { return e.type === "table"; })) {
      fail(name + " draws a table for trimmed run " + record.run_id);
    }
  });
});

// A full record fills the events table and the five aggregate tables.
const events = draw(parts.Events, { record: newest, demo: true, caps: caps });
const bodyRows = events.elements.filter(function (e) { return e.type === "tr"; }).length - 1;
if (bodyRows !== newest.rows.length) fail("Events drew " + bodyRows + " rows, expected " + newest.rows.length);
const aggregates = draw(parts.Aggregates, { record: newest, demo: true, caps: caps });
if (aggregates.elements.filter(function (e) { return e.type === "table"; }).length !== 5) {
  fail("Aggregates did not draw five sub-tables");
}

// A no_data run is a gap in the chart, never a bar of zero height.
const chart = draw(parts.ConnectionsChart, { record: newest, demo: true, series: seriesOk });
const bars = chart.elements.filter(function (e) { return e.props["data-part"]; });
if (bars.some(function (e) { return e.props["data-run"] === noData.run_id; })) {
  fail("the chart draws a bar for the no_data run");
}
if (!chart.elements.some(function (e) {
  return e.props["data-gap"] === "no_data" && e.props["data-run"] === noData.run_id;
})) fail("the chart does not mark the no_data run as a gap");
if (!chart.elements.some(function (e) { return e.type === "pattern"; })) fail("no hatch pattern");
if (!chart.elements.some(function (e) { return e.props["data-selected"]; })) {
  fail("the shown run is not highlighted in the chart");
}
const odd = draw(parts.ConnectionsChart, { record: newest, demo: true, series: withMalformed });
if (!odd.elements.some(function (e) { return e.props["data-gap"] === "malformed"; })) {
  fail("a malformed point is not drawn as a gap");
}
const empty = draw(parts.ConnectionsChart, { record: newest, demo: true, series: emptySeries });
if (empty.elements.some(function (e) { return e.type === "svg" && e.props.role === "img"; })) {
  fail("an empty series still draws a chart");
}

// The header names the plugin in full and reports where settings came from.
const header = draw(parts.Header, {
  health: {
    demo: true, mode: "demo", mode_setting: "auto", settings_source: "hermes",
    runs_dir: { location: "default", status: "missing", path: "/home/[user]/.hermes/plugin-data/hermes-snitchboard/runs", path_masked: true },
    settings_problems: []
  },
  settings: { allow_reveal: true }, runs: { items: [], total: 0 },
  payload: { demo: true, revealed: false, malformed: false, record: newest },
  selected: null, onSelect: function () {}, onMore: function () {}, onToggleReveal: function () {}
});
const headerText = header.text.join("");
["Hermes Snitchboard", "Settings from the Hermes configuration.",
  "Runs directory (default, missing): ", "/home/[user]/.hermes/plugin-data"].forEach(function (needle) {
  if (!headerText.includes(needle)) fail("the header lacks: " + needle);
});

// Tier C: volume, daemon state, rules and sockets draw from a full record.
const volume = draw(parts.Volume, { record: newest, demo: true, caps: caps });
const volumeRows = volume.elements.filter(function (e) { return e.type === "tr"; }).length - 1;
if (volumeRows !== newest.volume.rows.length) fail("Volume drew " + volumeRows + " rows");
const unmeasured = JSON.parse(JSON.stringify(newest));
unmeasured.volume = { available: false, note: "No byte counts were measured.", rows: [] };
const noVolume = draw(parts.Volume, { record: unmeasured, demo: true, caps: caps });
if (noVolume.elements.some(function (e) { return e.type === "table"; }) ||
    !noVolume.text.join(" ").includes("none has been estimated")) {
  fail("Volume does not state that unmeasured volume is unavailable");
}
const rules = draw(parts.RulesInForce, { record: newest, demo: true });
const ruleRows = rules.elements.filter(function (e) { return e.type === "tr"; }).length - 1;
if (ruleRows !== newest.aggregates.rules_detail.length) fail("Rules drew " + ruleRows + " rows");
const daemon = draw(parts.DaemonState, { record: newest, demo: true });
if (!daemon.text.join(" ").includes(newest.aggregates.node.daemon_version)) {
  fail("Daemon state omits the daemon version");
}
const sockets = draw(parts.Sockets, { record: newest, demo: true });
if (!sockets.elements.some(function (e) { return e.type === "table"; })) fail("Sockets drew no table");

// The export is built from loaded data only, quoted, and safe in a spreadsheet.
const csv = window.__HERMES_SNITCHBOARD_TEST__.csvForRecord;
const full = csv(newest).split("\r\n");
if (full[0] !== "ts,action,src,dst,dport,proto,uid,pid,process,activity,is_ai,severity") {
  fail("unexpected CSV header: " + full[0]);
}
if (full.length !== newest.rows.length + 2 || full[full.length - 1] !== "") {
  fail("the CSV does not hold one CRLF-terminated line per event row");
}
const hostile = JSON.parse(JSON.stringify(newest));
hostile.rows = [Object.assign({}, newest.rows[0], {
  process: "=cmd|' /C calc'!A0", activity: "a, \"quoted\"\nline", dst: "@host", src: "-1+1"
})];
const line = csv(hostile).split("\r\n")[1];
[",'=cmd|' /C calc'!A0,", ",'@host,", ",'-1+1,", "\"a, \"\"quoted\"\"\nline\""].forEach(function (cell) {
  if (!line.includes(cell)) fail("the CSV cell is not neutralised or quoted: " + cell);
});
const shortened = csv(trimmed).split("\r\n");
if (shortened[0] !== "severity,confidence,title,technique_id,tactic_id" ||
    shortened.length !== trimmed.detections.length + 2) {
  fail("a trimmed record does not export its shortened findings");
}

process.stdout.write("render smoke test passed\n");
