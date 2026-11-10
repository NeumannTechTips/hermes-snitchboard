# Hermes Snitchboard collector

`snitchboard_collect.py` reads one hour of connections from the OpenSnitch statistics database, analyses it, and writes one hash-chained run record into a runs directory. The Hermes Snitchboard tab reads that directory. Nothing else connects the two.

## What it is, and what it is not

The collector is separate from the plugin by design (PRD decision D3, requirement SP2). Hermes never loads it, never runs it and never needs access to the firewall database. You run it yourself, under your own account, normally from the systemd user timer in `systemd/`. The plugin reads only the records it leaves behind.

It does:

- open the OpenSnitch database read-only and check its layout before reading anything;
- select the connections recorded in one window of one hour;
- run the same analysis the tab displays (findings, beacons, novelty, agents, coverage) and seal the result into the chain;
- write the record atomically, then trim records older than the retention period.

It does not:

- write to, migrate or vacuum the OpenSnitch database, or change any firewall rule;
- open a network connection;
- delete a run record, ever;
- run as root, or need to.

Standard library only, Python 3.9 or later.

## Prerequisites

**The OpenSnitch GUI must write its database to a file.** By default the GUI keeps its database in memory, where nothing else can read it. In the GUI's preferences, set the database to a file and note the path. There is no default path, and the collector will not guess one (PRD OQ3): `--db` is mandatory.

Two properties of that database decide what a record can honestly say:

- **The GUI records connections only while it is running.** The daemon goes on enforcing rules without it, but nothing reaches the database. An hour in which the GUI was closed is collected as `no_data`, never as an hour with no traffic.
- **The GUI's own purge setting may delete old rows.** If it is set shorter than your backfill needs, the rows are gone and a late collection of that hour also yields `no_data`.

Missing hours therefore appear in the tab as `no_data` runs or as gaps in the coverage strip. Neither is ever shown as an all-clear.

The database file is normally owned by the account that runs the GUI. Run the collector under that same account.

## Usage

```
python3 collector/snitchboard_collect.py --db PATH --runs-dir PATH
                                         [--window-end ISO8601]
                                         [--settings PATH]
                                         [--dry-run] [--quiet]
```

| Flag | Meaning |
|---|---|
| `--db PATH` | The OpenSnitch database file. Mandatory, no default |
| `--runs-dir PATH` | Directory that holds the run records. Created with mode 0750 if missing, but its parent must already exist. An existing directory's mode is left alone |
| `--window-end ISO8601` | End of the one-hour window, with an explicit offset, for example `2026-11-10T07:00:00+00:00`. The window is the hour before it, end excluded. Default: the top of the current hour in this machine's local offset. A time in the future is refused |
| `--settings PATH` | A JSON object holding any of the plugin's own settings, validated by the same configuration module the plugin uses. `runs_dir` and `mode` are accepted and ignored. Any other key, including an analysis threshold, is refused, as is an unreadable or invalid file: each is a usage error |
| `--dry-run` | Analyse and print the counts and the run identifier that would be used. Writes nothing at all: no record, no lock, no trimming, and the runs directory is not created |
| `--quiet` | Suppress the normal summary line. Errors are still printed |

Examples, with placeholder paths:

```bash
# check what a run would produce, writing nothing
python3 collector/snitchboard_collect.py --db /path/to/opensnitch.sqlite \
    --runs-dir ~/snitchboard-runs --dry-run

# collect the hour that has just ended
python3 collector/snitchboard_collect.py --db /path/to/opensnitch.sqlite \
    --runs-dir ~/snitchboard-runs

# backfill one missed hour by hand
python3 collector/snitchboard_collect.py --db /path/to/opensnitch.sqlite \
    --runs-dir ~/snitchboard-runs --window-end 2026-11-10T07:00:00+00:00
```

Backfill one hour per call, on whole hours. A window that overlaps any stored record is refused, so an hour can be collected only once.

### Settings

The analysis happens here, when the record is written, not in the tab. Settings that shape it (`ai_process_names`, `agent_accounts`, `expected_services`, `provider_allowlist`, `unattended_hours`, `telemetry_destinations`) take effect only for records collected after you change them; stored records are sealed and are not re-analysed.

Give the collector the same values as the plugin. If the plugin reads its settings from `settings.json` in its data directory, point `--settings` at that same file. If they live in the Hermes configuration, copy the relevant keys into a JSON file for the collector.

`retention_days` and `trimmed_max_bytes` govern trimming as well as analysis. If the collector trims under a larger `trimmed_max_bytes` than the plugin is configured with, the tab reports those trimmed records as malformed.

The analysis thresholds in `snitchboard/config.py` are not settings in this release, for the collector or the plugin. The collector refuses them rather than applying them, because the tab validates every record against the default caps and would report a record built under different ones as malformed.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | A record was written, whatever its status (`ok`, `partial` or `no_data`), or a dry run completed |
| 1 | Refused or failed: the window is already collected or overlaps a stored record, the window end is in the future, the lock is held, the newest stored record is unreadable or invalid, the clock is behind the newest record, writing failed, or a trim failed (see Retention) |
| 2 | Usage error: a missing or malformed flag, or an unreadable or invalid settings file |

Under systemd, exit code 1 leaves the service in the failed state, so `systemctl --user --failed` shows it.

### Output

The summary line and every error carry only counts, the run identifier and plain status words, for example:

```
run-20261110T070200Z status=ok connections=123 destinations=17 detections=2
refused: window already collected
```

It never prints an address, host name, process path, file path, account name or raw exception text, because the journal may be readable by others. The records themselves do contain addresses, host names, process paths and account names; that is what the file permissions below are for.

Account names come from resolving each connection's uid on this machine, so that `agent_accounts` can match by name. The tab masks addresses, host names and home paths by default, but in this release it shows account names in clear. Masking them is a v0.2.0 item.

## Record status

| Status | Meaning |
|---|---|
| `ok` | Every column the collector reads was present and every row in the window was read. A note may still record something that changes nothing in the record, such as an absent column the collector does not read, or a rule operand that was shortened. The hour counts as covered |
| `partial` | A record was written, but something it would have contained was missing or skipped, and the note says what: a column the collector reads or one of the nodes, rules and sockets tables absent, rows whose time, action, port, protocol or destination could not be read (counted and skipped), or daemon counters that could not be parsed. Analysed and stored, but the hour is **not** counted as covered |
| `no_data` | Nothing could be collected, and the note says why: the file is missing or not a database, the database stayed busy, a required column is absent, the time format was not recognised, or no connections were recorded in the window. Not covered |

This is how the collector meets risk R6. The OpenSnitch database layout varies between versions, so the collector reads the columns of each table before querying it. It requires `time`, `action`, `protocol`, `dst_ip` and `dst_port` in the connections table, and records `no_data` with an explanation when one is absent. It also reads `node`, `src_ip`, `dst_host`, `uid`, `pid` and `process`, and the nodes, rules and sockets tables; when one of those is absent the run is `partial` and the note names it. The columns it never reads (`src_port`, `process_args`, `process_cwd` and `rule`) are named in the note when absent, but they do not lower the status, because nothing in the record depends on them and an older database would otherwise show every hour as uncovered. It never reads the lifetime counter tables (hosts, procs, addrs, ports, users), so the connection counts and aggregates in a record describe its window. Only the daemon state panel carries lifetime figures, the ones the daemon reports about itself.

If the window holds connections from more than one OpenSnitch node, all of them are included, the note says how many nodes there were, and the daemon state describes the node with the most rows.

## What a record cannot contain

- **Volume.** The OpenSnitch database holds no byte counts. The volume panel says volume is unavailable for collected records, and no figure is estimated (FR7).
- **Process arguments.** Deliberately not stored, because arguments can carry secrets. A record keeps the process path only.
- **Long rule operands.** A rule's `operator_data` longer than 512 characters is cut at 512 and marked `[truncated from N characters]`, and the note says how many rules were shortened. Without the cap, one rule with a large inline list could push every record past the 200 KiB full-record cap and stop collection.
- **Long-period beacons.** A one-hour window holding eight contacts caps the observable mean interval at roughly 8.5 minutes, so slower heartbeats are not detected (PRD 7.4).

## Time interpretation

The collector samples the connections table's time column and classifies its format before selecting rows.

- A time with no offset, such as `2026-11-10 07:15:42`, is read as **this machine's local time**, using the local timezone rules including daylight saving. Run the collector under the same timezone as the GUI; the systemd user manager normally inherits the system timezone, and the service file shows how to set `TZ` if it must differ. Times without an offset cannot tell the two copies of the repeated hour apart when clocks go back, so rows from that hour may be placed in the wrong window.
- A time with an explicit offset keeps it.
- A format the collector does not recognise gives a `no_data` record saying so. Rows whose time does not parse in an otherwise readable table are skipped, counted and reported in a `partial` note.

Timestamps in the record keep their offset and are never relabelled as UTC (FR10).

## Read-only guarantees

The database is opened through SQLite's read-only URI mode, and the connection is then set to `query_only`. The collector never writes, migrates or vacuums it. If the GUI is writing at that moment and the database is locked, the collector retries a few times with a short back-off and otherwise records `no_data`, "the database was busy". The tab never opens the database at all.

## File permissions and a separate Hermes account

Records are written with mode 0640, and a runs directory the collector creates gets mode 0750. They are readable by you and your group, and by nobody else.

If Hermes runs under a different account from yours, that account needs read access to the records and search access to the directory and every directory above it. Two ways to give it:

- Add the Hermes account to your primary group. Simple, but it also lets that account read anything else of yours that is group-readable.
- Narrower: create a dedicated group, make it the group of the runs directory, and set the directory's setgid bit so new records inherit the group:

  ```bash
  install -d -m 2750 -g snitchboard-readers /path/to/snitchboard-runs
  ```

  The collector never changes the mode of an existing directory, so this survives.

A home directory with mode 0700 blocks another account from reaching anything inside it. In that case place the runs directory outside your home.

## Pointing the plugin at the directory

Set `runs_dir` in the plugin settings (`plugins.entries.hermes-snitchboard.settings` in the Hermes configuration) to the absolute path of the runs directory. A relative path is reported as invalid and no records are read. If `runs_dir` is left empty the plugin reads `<HERMES_HOME>/plugin-data/hermes-snitchboard/runs`, which suits a single-account setup: pass that path to `--runs-dir`.

The plugin's `/health` route reports which directory the tab resolved and whether it could read it. With `mode` set to `auto`, an empty or unreadable directory falls back to demonstration data; set `mode` to `live` once records exist, so that a later problem shows as an empty live view rather than as demonstration data.

## Locking

Each run takes a lock file, `.snitchboard-collect.lock`, in the runs directory, holding the collector's process ID. It is removed when the run ends, including when systemd stops it with SIGTERM. A second collector that finds the lock refuses with "refused: lock held" and exits 1.

A crash, a SIGKILL or a power loss can leave the lock behind, and every later run then refuses. To clear it:

```bash
systemctl --user status snitchboard-collect.service    # confirm nothing is running
pgrep -f snitchboard_collect.py                        # should print nothing
rm ~/snitchboard-runs/.snitchboard-collect.lock
```

With no collector running, any `.snitchboard-*.tmp` file in the directory is debris from an interrupted write and can be removed too. The tab ignores both.

## Retention and trimming

After writing its record, the collector looks for full records whose window ended more than `retention_days` ago (default 14) and trims each one in place. Records are trimmed, never deleted, so the chain survives: a trimmed record keeps its original digest as `sealed_sha256` and its list of destinations, so novelty scoring still works. The shortened summary it keeps is not covered by the chain, and the tab labels it as a derived aid rather than evidence (PRD D8).

Trimming fails loudly (PRD D9). If a record's destinations alone will not fit within `trimmed_max_bytes`, that record is left in full form, the collector prints `trim failed:` and the run identifier, carries on with the others, and exits 1, even though the new record was written. Raise `trimmed_max_bytes` (up to 204800) in both the collector's and the plugin's settings to resolve it. Lowering it later makes records already trimmed under the larger cap show as malformed, which is deliberate.

Size: a full record is capped at 200 KiB and a trimmed one at `trimmed_max_bytes`, so an hourly timer at the defaults needs at most about 70 MB for the fortnight of full records and about 70 MB a year after that. The tab lists the newest 10,000 records. The collector never deletes a record; one removed by hand from the middle of the history appears as a break when the chain is verified.

## Running the tests

From the repository root:

```bash
python3 -m unittest tests.test_collector -v          # the collector alone
python3 -m unittest discover -s tests -t .           # the whole suite
```

The tests build a throwaway database from `tests/fixtures/opensnitch_sample.sql`, which holds documentation-range values only (192.0.2.x, example.com). They need no OpenSnitch, no network and no Hermes.
