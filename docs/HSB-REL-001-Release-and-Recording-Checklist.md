# HSB-REL-001 Release, Recording and Submission Checklist

**Project:** Hermes Snitchboard
**Maintainer:** NeumannTechTips
**Version:** 1.0
**Status:** Active
**Governs:** HSB-PRD-001 section 11, catalogue submission and the hackathon entry

---

## 1. Deadline and running order

The entry closes at **22:00 UTC on Wednesday 11 November 2026**, which is **09:00 on Thursday 12 November in Sydney**. Everything below is ordered so the last irreversible step happens with margin rather than at the edge.

| Window | Step | Reversible |
|---|---|---|
| Tuesday afternoon | Decide the collector question (section 2) | Yes |
| Tuesday evening | Capture stills (section 5) and commit them | Yes |
| Tuesday evening | Record and cut the video (section 6) | Yes |
| Wednesday early | Code freeze, publication gate, make public, tag (section 7) | Public is hard to undo |
| Wednesday morning | Open the catalogue pull request (section 8) | Yes |
| Wednesday afternoon | Post the video on X (section 9) | Deletable, not retractable |
| Wednesday by 20:00 Sydney | Submit the Typeform (section 10) | One submission |

---

## 2. The open decision: viewer only, or viewer plus collector

The repository ships the viewer. The `collector/` directory holds nothing but an empty `systemd/` placeholder, so `mode: live` currently has no way to produce a record and the tab can only ever show demonstration data.

**Option A, viewer only.** Say so plainly in the README and the catalogue entry, publish the record schema so anyone can write a collector, and promise one in v0.2.0. Honest, and it costs nothing today.

**Option B, add the reference collector.** A single standard-library script that reads the OpenSnitch statistics database, builds one run record per hour, seals it into the chain and trims older records. The engine already holds the schema, the canonical form, the chain and the redaction rules, so the collector is a query plus an assembly step rather than new logic.

The recommendation is **Option B if the time exists, Option A if it does not**. A reviewer who installs the plugin and finds it can only show synthetic data will read it as a mock-up. Option A is defensible; Option B is the difference between a demonstration and a tool. Nothing else in this checklist changes either way.

---

## 3. What must never appear on screen

This list governs both the stills and the video. A single frame is enough to leak any of it.

### 3.1 Identity and machine

- The terminal prompt, which carries the account name and the host name.
- The browser title bar or window list showing the host name.
- The address bar beyond `127.0.0.1:9119`. Press **F11** for full screen and the bar disappears.
- Bookmarks bar, browser profile avatar, extension icons, other tab titles.
- The desktop wallpaper, panel, system tray, clock widget and any application launcher.
- Email addresses anywhere, including the GitHub account strip if a repository page is shown.
- Any file manager, editor or terminal window, even behind the browser.

### 3.2 Hermes and the plugin

- The **Reveal** control stays **off** for the entire recording. Masking is the default and the recording must show the default.
- Sidebar sections that list real session names or file paths. Stay on the Hermes Snitchboard tab.
- `~/.hermes/logs/errors.log` and anything else from the Signal gateway. It contains third-party contact names and partially masked mobile numbers. Do not open it, do not tail it, do not leave a terminal showing it.
- The settings line reports the runs directory. Confirm on screen that it reads `/home/[user]/...` and not a real account name before recording.

### 3.3 Before pressing record

- [ ] Do Not Disturb enabled, notifications suppressed.
- [ ] Every application other than the browser closed.
- [ ] A fresh browser window with one tab, bookmarks hidden, full screen.
- [ ] Dashboard restarted and serving the tagged commit.
- [ ] Tab opened at `http://127.0.0.1:9119/hermes-snitchboard` and scrolled to the top.
- [ ] Demonstration badge visible on the panels, confirming no live data is on screen.
- [ ] One dry run watched back in full before the real take.

---

## 4. Capture tooling

Stills on Fedora KDE come from **Spectacle**: `Ctrl` + `Shift` + `Print` gives a rectangular region, and the window capture mode gives a clean window without the panel. Save as PNG.

Video comes from **OBS Studio** or KDE's own screen recorder. Record the browser window only, not the full desktop, so the panel and tray never enter frame. Record at 1920 by 1080 and 30 frames per second; anything heavier is wasted on X.

---

## 5. Still captures

Five images, saved into `docs/screenshots/` with exactly these names, because the catalogue entry already points at them:

| File | Frame |
|---|---|
| `01-summary-and-coverage.png` | The page header through the coverage strip, with the two gap hours visible |
| `02-findings.png` | Two or three findings, including one HIGH with its ATT&CK block, evidence lines and recommendation |
| `03-beacons-and-novel.png` | The beacons table showing both readings in the assessment column, plus the top of novel destinations |
| `04-chart-and-events.png` | The connections chart with the dashed `no_data` column, plus the top of the events table |
| `05-integrity.png` | The integrity panel after pressing Verify chain, showing CHAIN INTACT and the trimmed-record note |

Rules for every frame: masking on, demonstration badge in shot where the panel carries one, no browser chrome, width 1200 to 1600 pixels. Crop to the card, not to the whole viewport, so the text stays readable on the catalogue page.

The banner at `docs/assets/banner.png` is 1200 by 600, which is the 2:1 shape the catalogue wants for `image:`.

---

## 6. The video

Under 90 seconds, posted on X, tagging `@NousResearch`.

Captions on screen are safer than live narration: they cost nothing to redo, they read correctly with sound off, which is how most of X watches video, and they cannot wander off script.

### 6.1 Shot list

| Time | On screen | Caption |
|---|---|---|
| 0:00 to 0:08 | Hermes sidebar, click **Hermes Snitchboard** | Hermes tells you what it did. This tells you what your machine actually connected to. |
| 0:08 to 0:20 | Summary tiles, then the coverage strip | One slot per hour. An hour with no collection shows as a gap, never as a quiet hour. |
| 0:20 to 0:42 | Scroll through findings; rest on the unattributed-process finding and the outbound-transfer finding | Every finding carries the ATT&CK technique, the records behind it, and one thing to do next. |
| 0:42 to 0:56 | The beacons table, assessment column in view | A heartbeat gets both readings. Nothing is called malicious on rhythm alone. |
| 0:56 to 1:12 | Integrity panel, press **Verify chain**, let the result land | Every run is hash-chained. Alter a stored record and the chain says so. |
| 1:12 to 1:22 | Scroll up briefly to show masked values and the demonstration badge | Addresses masked by default. This is synthetic data in documentation ranges. |
| 1:22 to 1:28 | Still card: the banner | Hermes Snitchboard. Unofficial community plugin. |

Total 88 seconds. If a shot runs long, take it out of the findings block, which is the only one with slack.

### 6.2 Recording discipline

- Scroll slowly and in one direction. Fast scrolling reads as noise once the video is compressed.
- Pause for a beat after each click so the viewer sees the result, not the transition.
- Do not move the mouse while a caption is on screen.
- Watch the finished cut once at full size and once at phone size before posting.

### 6.3 Draft post

> Built **Hermes Snitchboard** for the Hermes Agent plugin hackathon.
>
> Your agent can tell you what it did. This tells you what your machine actually connected to: OpenSnitch connection evidence as plain-language findings, mapped to MITRE ATT&CK, with every run hash-chained so edits to stored history are detectable.
>
> Read-only, local, no telemetry.
>
> @NousResearch
>
> github.com/NeumannTechTips/hermes-snitchboard

---

## 7. Code freeze and publication gate

Run these in the VS Code terminal, from the project folder. Stop at the first one that does not do what it says.

```bash
cd ~/Claude/projects/hermes-snitchboard

# 1. Nothing uncommitted, and the tree matches the remote.
git status --porcelain && git log --oneline -1 && git fetch -q origin && git rev-list --left-right --count HEAD...origin/main

# 2. Every test passes.
python3 -m unittest discover -s tests -t . 2>&1 | tail -3

# 3. The publication gate. This must print CLEAN before the repository goes public.
python3 tools/scan_history.py
```

The scanner reads `.scan-words`, which is gitignored and must hold the real values being checked for. If it reports the word check as SKIPPED, the file is missing and the gate has not actually run.

Then, in the Hermes account's shell:

```bash
sudo -iu hermes bash -lc 'cd "$HOME/.hermes/plugins/hermes-snitchboard" && git pull -q && hermes plugins validate .'
```

Record what the security scan reports. A `caution` result needs a sentence in the pull request explaining it. A `dangerous` result stops the submission.

Once all four are clean:

- Make the repository public in GitHub settings.
- Re-enable branch protection on `main`.
- Tag and push:

```bash
cd ~/Claude/projects/hermes-snitchboard
git tag -s v0.1.0 -m "Hermes Snitchboard v0.1.0"
git push origin v0.1.0
git rev-parse v0.1.0^{commit}
```

That last command prints the 40-character SHA the catalogue entry needs. Copy it exactly.

---

## 8. The catalogue pull request

```bash
# Fill the pin into the entry. Replace SHA below with the output of git rev-parse.
cd ~/Claude/projects/hermes-snitchboard
SHA=<the 40-character sha>
sed -i "s/RELEASE_SHA_GOES_HERE/$SHA/g" ~/Downloads/hermes-snitchboard.yaml
grep -c RELEASE_SHA_GOES_HERE ~/Downloads/hermes-snitchboard.yaml   # must print 0
```

Then fork `NousResearch/hermes-agent`, add the file at `plugin-catalog/hermes-snitchboard.yaml`, and open the pull request.

The pull request description carries the disclosure the admission rules ask for:

- What it reads, what it writes, what it never touches.
- That it registers no tools, hooks or middleware.
- That it makes no network call and sends no telemetry.
- The result of `hermes plugins validate`, including the scan verdict.
- That the maintainer owns the plugin repository, which satisfies the owner-submission rule.

Open this on Wednesday morning. A failing CI check needs time to fix, and the afternoon is the margin for it.

---

## 9. Posting the video

Post from the NeumannTechTips account. Tag `@NousResearch`. Keep the repository link in the post body rather than a reply, because the Typeform asks for the post link and a judge should reach the code from the same place.

Copy the post URL the moment it is live.

---

## 10. The Typeform

`https://form.typeform.com/to/FwJLvOln`

Both links go in: the pull request URL and the X post URL. Submit by **20:00 Sydney time on Wednesday**, which leaves thirteen hours of margin against the close.

---

## 11. Final gate

- [ ] Repository public, branch protection on, `v0.1.0` tagged and pushed
- [ ] `tools/scan_history.py` printed CLEAN with `.scan-words` present
- [ ] `hermes plugins validate` passed and its scan verdict recorded
- [ ] Five screenshots and the banner committed at the tagged commit
- [ ] Catalogue entry pinned to the 40-character SHA, no placeholder left
- [ ] Pull request open with the disclosure
- [ ] Video under 90 seconds, posted, tagging @NousResearch
- [ ] Typeform submitted with both links

---

## 12. Change record

| Version | Date | Change |
|---|---|---|
| 1.0 | 10 November 2026 | First issue |
