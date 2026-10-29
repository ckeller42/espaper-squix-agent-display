# SDD ledger — plan: docs/superpowers/plans/2026-10-28-espaper-display-server.md

Spec: docs/superpowers/specs/2026-10-28-espaper-agent-display-design.md (read)
Branch: feat/display-server (in place, not a worktree)

Ruling: work in place on `feat/display-server` rather than a new worktree — the user
is on PR-only flows, we are not on `main`, and agent-deck already owns
`.worktrees/fork-squix`; a second worktree risks confusing that tooling.
Cost if wrong: the main checkout carries uncommitted work mid-plan; recoverable
by `git stash` or branching again.

## Pre-flight conflict scan

### Cross-task pairs (shared file or interface)

| Pair | Produces → Consumes | Finding |
|---|---|---|
| T1 → T4 | `pack_screen`, `PAYLOAD_SIZE` → render tests | consistent |
| T1 → T7 | `pack_screen`, `PAYLOAD_SIZE` → parity round-trip | consistent |
| T2 → T3 | `sources.py`: `Reading`/`Source` → `fetch_with_fallback` | same file, additive; consistent |
| T2 → T4 | `Reading` → `render(recipe, readings, now)` | consistent |
| T3 → T4 | `age_of` → staleness shown on screen | consistent |
| T4 → T5 | `Recipe`, `render` → `Store.approve` | consistent **after pre-flight fix** (see ruling R2) |
| T5 → T6 | `app.py`: device routes → preview routes | same file, additive; consistent |
| T5 → T8 | `Store.approve/forget/last_telemetry` → fake-device tests | consistent **after R2** |
| T7 → T8 | `decode_payload` → `FakeDevice.wake()` | consistent |
| T5 → T9 | live server → native firmware tests | consistent |
| T9 → T11 | `[env:native]` → `Firmware host tests` CI job | consistent |
| T1–T8 → T11 | pytest suite → `scripts/gate.sh` + CI | consistent |

### Per-task self-consistency

| Task | Finding |
|---|---|
| T1 | tests use `blank_white_image()` / `blank_black_image()` helpers the task never defines → R1 |
| T2 | tests call `_parse(...)` but the Interfaces block lists only `fetch()` → R3 |
| T3 | fixtures `FailingSource`, `OLD_READING`, `FIXED_NOW` undefined → R1 |
| T4 | `text_drawn` helper — task says implement it in the test module; self-consistent |
| T5 | fixtures `client`, `dev`, `auth`, `fresh`, `store` undefined → R1 |
| T6 | consistent |
| T7 | `sample_image` fixture undefined → R1 |
| T8 | `OLD_ID` and `d` referenced before definition in the test sketches → R1 |
| T9 | largest task by far: Arduino/WiFi host shims are not a one-sitting job → R4 |
| T10 | documentation only; consistent |
| T11 | consistent |

### Rulings

Ruling R1: test fixtures and helpers named but not defined in the plan's test
sketches are the implementer's to write. The plan pins assertions and values, not
scaffolding — per the writing-plans rule that a step need only be unambiguous.
Cost if wrong: an implementer asks a question instead of proceeding; cheap.

Ruling R2: Task 5's `Store` interface was missing `approve`, `forget`,
`pending_recipe`, `is_approved` and `last_telemetry`, all of which Task 8 calls.
Fixed in the plan before execution. Cost if wrong: none — the alternative was a
subagent stranded mid-task.

Ruling R3: `_parse(payload)` is a required part of Task 2, not an implementation
detail — the tests depend on parsing without network. Implementers must expose it.
Cost if wrong: tests would need live HTTP, making CI flaky and slow.

Ruling R4: Task 9 (host shims + native env) is flagged as the likeliest BLOCKED
task. If the implementer reports it cannot shim `WiFiClient` cheaply, the fallback
is to extract `dissectUrl` and the header parsing into a header-only unit tested
natively, and to cover the socket path via Task 8's fake device instead. Cost if
wrong: weaker firmware-level e2e than the spec asks for; the protocol is still
covered by Tasks 7 and 8.

## Progress

Task 1: implementer DONE_WITH_CONCERNS (commit 5e14b9c, 5/5 tests passing, output pristine)
Task 1: concerns triaged — none are correctness or scope problems; proceeded to review.
  - RED failed with ModuleNotFoundError rather than the brief's predicted missing-attribute
    error. Same cause (the module did not exist); TDD evidence still valid.
  - `pythonpath = ["."]` added to pytest config so the package imports with no build backend.
  - `server/uv.lock` and `server/.gitignore` committed beyond the brief's `git add` list.
Task 1: Ruling: version byte = 1. The brief leaves it unspecified and the firmware only logs
  it (`drawPalettedBitmapFromFile` reads `buf[0]` and prints it, never validates). Fixing a
  value now means a later format revision has somewhere to go.
  Cost if wrong: none today; a future format v2 would need the device to start checking it.
Task 1: Ruling: keep `server/uv.lock` committed. It is the reproducibility guarantee for the
  toolchain, matching how this repo already pins the PlatformIO platform and the Docker base
  image. Cost if wrong: lockfile churn in diffs, and Dependabot does not track uv.lock.
Task 1: review package review-a0bbd4e..5e14b9c.diff; task reviewer dispatched (sonnet)
Task 1: review clean — Spec compliant, quality Approved, 0 Critical, 0 Important.
  Reviewer independently checked the packing against lib/MiniGrafx/src/MiniGrafx.cpp:1011-1077
  (header, bit order, row reset at :1074, bpp rejection at :1027) and confirmed the packer is
  the exact inverse of the device reader.
Task 1: controller resolved the reviewer's two ⚠️ items (it could not see the end of the diff):
  `uv run pytest -q` -> 5 passed in 0.02s. uv.lock resolves. Both confirmed, no gap.
Task 1: minor (deferred): test_packer.py:104-108 does not assert the version byte (header[0]).
Task 1: minor (deferred): no wrong-mode test, e.g. Image.new("L", (296,128)); code handles it.
Task 1: minor (deferred): packer.py:59 line ~105 chars.
Task 1: complete (commits a0bbd4e..5e14b9c, review clean)
Task 2: BASE=5e14b9c, implementer dispatched (sonnet). Carried: Ruling R3 (_parse is part of
  the interface), live-captured field shapes for both providers, and the Open-Meteo trap that
  current.time has no offset suffix and must be combined with utc_offset_seconds.
Briefs staged for Tasks 4-11.

## Goal set by Christoph (2026-10-28, mid-execution)

"I can see the new display on the epaper device and on the webserver the layout.
You show me the link that I can open and an ascii art of the screen."

Definition of done, four parts:
  1. the screen visible on the ESPaper itself  -> needs the firmware plan (DEV build + reflash)
  2. the layout visible on the web server      -> Task 6
  3. a link I hand over that he can open       -> Task 6
  4. ASCII art of the screen, shown in chat    -> NEW, plan amended

Ruling: amend Task 6 rather than add a task. `render_ascii(image, cols=74)` lands in
render.py with a `GET /preview.txt` route, plus three tests: exact width, roughly square
aspect (16 rows), and that an all-white screen renders blank rather than solid -- ink is
bit 0, and that polarity error is invisible in the PNG but obvious in ASCII.
Cost if wrong: Task 6 grows slightly; no cross-task interface changes.

Note: part 1 is NOT reachable from this plan alone. The device currently runs the PROD
build pointing at espaper.com. It needs the DEV build re-pointed at the server plus a
manual flash -- which the spec puts after Tasks 7-9 are green.
Task 2: implementer DONE_WITH_CONCERNS (commit 13b41c4, 14/14 tests passing)
Task 2: controller check — Yahoo returned HTTP 200 for me, so the "Too Many Requests" the
  implementer hit was transient (its own repeated calls). Evidence passed to the reviewer.
Task 2: review — Needs fixes. 1 Important, 7 Minor. Spec compliant on interface; reviewer
  independently verified the Open-Meteo offset DIRECTION (sources.py:84-85), not merely that
  the datetime is aware — 19:45+01:00 == 18:45 UTC, which an inverted offset would fail.
Task 2: minor (deferred): Yahoo error shape (chart.result: null) raises bare TypeError.
Task 2: minor (deferred): `timezone` param shadows the datetime.timezone import (sources.py:57).
Task 2: minor (deferred): hand-rolled frozen check instead of pytest.raises(FrozenInstanceError).
Task 2: minor (deferred): `extra` dict makes the frozen dataclass shallowly immutable.
Task 2: minor (deferred): currency formatting wrong for JPY/GBp; fine for NVDA in USD.
Task 2: minor (deferred): no negative-offset or DST-summer test; direction already pinned.
Task 2: minor (deferred): fetch() untested; httpx.MockTransport would cover URL/params/UA.
Task 2: Ruling: the `extra` keys the implementer chose are now a cross-task contract —
  weather high/low/precipitation/weather_code, quote previous_close/change/exchange. Task 4
  will be told these names. Cost if wrong: Task 4 needs a rename round.
Task 2: fix round 1/5 dispatched — Important 1 only (re-capture the Yahoo fixture from the
  live API). Minors explicitly excluded from the round.
Task 2: fix round 1/5 (1 addressed, 0 open; commits 13b41c4..f1b5bb7)
  Re-reviewer verified the capture is genuine by its own forensics, not the report's word:
  float32 artifacts (215.85000610351562), incidental unread fields (firstTradeDate,
  currentTradingPeriod, validRanges), co-varying arithmetic (215.85-217.94 = -2.09, and
  -2.09/217.94 = -0.959% matching regularMarketChangePercent), and a timestamp inside the
  session window 1793194200..1793217600. No new breakage; sources.py untouched.
Task 2: controller ran the full suite the implementer skipped this round -> 14 passed.
Task 2: complete (commits 5e14b9c..f1b5bb7, review clean)
Task 3: BASE=f1b5bb7, implementer dispatched (sonnet).
Task 3: implementer DONE_WITH_CONCERNS (commit 6b7003c, 21/21 passing, no network in tests)
Task 3: Ruling: PROMOTE the deferred Task 2 minor (QuoteSource._parse raises bare TypeError on
  Yahoo's error shape) into Task 3's scope, and drop TypeError from the fallback catch set.
  Reason: catching TypeError to absorb a known API shape silently swallows genuine programming
  bugs inside a source and renders them as "stale data" — the exact failure this task exists to
  prevent, inverted. Addressed BEFORE review per the DONE_WITH_CONCERNS rule (correctness).
  Cost if wrong: a Yahoo error shape that is not a ValueError escapes the fallback and the
  render fails loudly instead of degrading. Loud is the better failure here.
Task 3: Ruling: keep the Unix-epoch placeholder for a no-previous-reading Reading. A ~56-year
  age is ugly but honest and can never read as fresh. Cost if wrong: Task 4 must special-case
  the em dash — recorded below as a cross-task contract.
Task 3: CROSS-TASK CONTRACT for Task 4: a Reading with value "—" is the no-data placeholder;
  render it WITHOUT its age (observed_at is the Unix epoch). fetch_with_fallback's second
  return value (is_stale) is the signal to show an age at all.
Task 3: minor (deferred): fetch failures are not logged.
Task 3: fix (pre-review, correctness) commit f4e4612 — _parse raises ValueError with Yahoo's
  code/description; TypeError dropped from the catch set. 25/25 passing.
Task 3: review — Approved, 0 Critical, 0 Important, 5 Minor. Reviewer verified the new tests
  genuinely constrain behaviour (reverting the fix fails them), so the missing RED run did no
  harm. Confirmed httpx.HTTPError covers exactly the transport set, and that KeyboardInterrupt
  and RuntimeError propagate.
Task 3: controller RESOLVED the reviewer's ⚠️ (it could not see Reading/_money in the diff):
  NO_DATA.extra IS shared mutable state. Verified by running it — NO_DATA.extra['x']='1'
  mutates the module-level singleton that fetch_with_fallback returns on every no-data
  fallback (sources.py:131,139). Reading's own default_factory is fine; the singleton is not.
  Treated as a confirmed gap -> enters the fix loop.
Task 3: Ruling: PROMOTE reviewer Minor 1 (null-field Yahoo shapes crash: "chart": null,
  regularMarketPrice null, regularMarketTime null, out-of-range timestamp) into the fix round.
  Reason: the spec names "never a blank panel and never a crash" as a requirement; these are
  known crash paths, not polish. Also the direct consequence of my own earlier TypeError
  ruling, which moved that responsibility into _parse.
  Cost if wrong: one extra round on a task already approved.
Task 3: minor (deferred): no httpx.HTTPStatusError / raise_for_status test case.
Task 3: minor (deferred): fetch() itself never exercised (MockTransport would cover it).
Task 3: minor (deferred): loop-in-test hides which case failed; use pytest.mark.parametrize.
Task 3: minor (deferred): TRANSPORT_AND_PARSE_ERRORS name omits ValueError and IndexError.
Task 3: minor (deferred): consider a dedicated SourceParseError raised only inside _parse.
Task 3: minor (deferred): split fallback helpers out of sources.py if a third provider lands.
Task 3: fix round 1/5 dispatched — confirmed ⚠️ (NO_DATA shared mutable) + promoted Minor 1.
Task 3: fix round 1/5 (2 addressed, 0 open; commits f4e4612..0132cb8). RED shown: 6 failed,
  20 passed before the fix; 31 passing after. NO_DATA singleton replaced by a _no_data()
  factory; _parse validates chart/currency/price/time with chained ValueError.
Task 3: Ruling: ONE more round (2/5) to close the remaining instances of the same crash class
  the re-reviewer found in untouched code — null/non-dict meta or result[0] (sources.py:37-38)
  and non-numeric chartPreviousClose (sources.py:55). Reason: "never a blank panel and never a
  crash" is a spec requirement, and fixing the class beats meeting it again at every review.
  Cost if wrong: one short round on an already-approved task.
Task 3: Ruling: do NOT wrap _parse's body in a blanket `except Exception -> ValueError`, even
  though it closes the class in one line. It would re-introduce exactly what dropping TypeError
  removed: a programming bug inside _parse silently rendered as "stale data" forever.
  Enumerated guards are the deliberate choice; tedium is the price of loud failure.
  Cost if wrong: a future unlisted Yahoo shape crashes the render instead of degrading.
Task 3: minor (deferred): aliasing on the previous-reading path — fetch_with_fallback returns
  `previous` itself (sources.py:89), so a caller mutating a fallback's extra affects the next
  fallback. Caller's own object, not shared state. Mitigated by contracting Task 4 not to
  mutate extra.
Task 3: CROSS-TASK CONTRACT for Task 4 (addition): never mutate Reading.extra. Treat Readings
  as read-only; copy if you need to annotate.
Task 3: fix round 2/5 (1 addressed, 0 open; commits 0132cb8..4bf1b8a). RED: 5 failed, 27
  passed; 37 passing after. No-blanket-catch constraint verified RESPECTED. Optional
  chartPreviousClose confirmed still parsing — guard uses `previous is not None and not
  isinstance(...)`, with both null and absent cases pinned.
Task 3: fix round 3/5 dispatched — last residual of the class: a truthy non-indexable top-level
  `result` ({"chart": {"result": 5}}) reaches result[0] and raises TypeError. A list guard
  closes it definitively: after an isinstance(list) check, [0] can only IndexError (already
  caught) or succeed. Declared the LAST round for this class.
Task 3: minor (deferred): isinstance(True, int) is True, so a boolean regularMarketPrice or
  chartPreviousClose passes the numeric guards. Renders a wrong number rather than crashing;
  no plausible API emits it.
Task 3: fix round 3/5 (1 addressed, 0 open; commits 4bf1b8a..5d784a6). RED: 2 failed, 32
  passed; 39 passing after. Reviewer verified the closure argument against the code: guard at
  sources.py:107-108 precedes the index at :109 and checks chart["result"] itself. Non-list
  truthy values rejected at :107, falsy at :101, so only lists reach [0] -> IndexError (caught)
  or success. Class genuinely closed. No blanket catch introduced.
Task 3: minor (deferred): chart["error"] truthy non-dict (e.g. a string) with falsy result ->
  AttributeError at sources.py:105, outside the catch set. Same escape class, neighbouring
  branch. DEFERRED BY MY OWN DECLARATION that round 3 was the last for this class — recorded
  here for the final whole-branch review to triage rather than opening round 4.
  Cost if wrong: an exotic Yahoo error payload crashes the render instead of degrading.
Task 3: complete (commits f1b5bb7..5d784a6, review clean)
Task 4: BASE=5d784a6, implementer dispatched (sonnet).
Task 4: implementer DONE_WITH_CONCERNS (commit 86240e7, 65/65 passing, no warnings)
Task 4: ENVIRONMENT DEFECT on this machine (bar), not in the code: ~/.zshenv:3,6 set
  UV_CACHE_DIR and PRE_COMMIT_HOME under /Volumes/External, which is not mounted, so `uv run`
  and pre-commit fail for every subagent. Ruling: do NOT edit the user's dotfiles (outside the
  worktree, affects their whole machine). Instead pass writable overrides in each remaining
  dispatch. Cost if wrong: implementers keep hitting it and work around it ad hoc.
  Reported to the user separately.
Task 4: review — Needs fixes. 0 Critical, 3 Important, 11 Minor. Reviewer verified rather than
  accepted: clipping is structural (per-panel canvas at render.py:112,164, not a length check);
  timezone test is non-tautological (asserts 19:02 CET AND 03:02 JST); em-dash path returns
  early at render.py:76-78 so no epoch age can print; extra never mutated (render.py:72-74,
  pinned at test_render.py:116-119); it even round-tripped a PNG against Pillow 13 to confirm
  info["text"] does not leak into saved bytes.
Task 4: controller RESOLVING ⚠️ 1 — Layout C's ~60/40 weights and the Open-Meteo attribution
  are properties of the SHIPPED recipe, and this diff ships none (tests/recipes.py is a
  fixture). The plan has no task that ships a real recipe. PLAN DEFECT.
  Ruling: Task 6 must ship an example recipe (weather + NVDA, layout C weights, attribution)
  so the preview page and the ASCII art show something real — which is what Christoph's goal
  requires. Recorded here; Task 6's dispatch will carry it.
  Cost if wrong: the preview renders an empty or placeholder screen and the goal is unmet.
Task 4: controller RESOLVING ⚠️ 2 — tzdata is a runtime dep but zoneinfo prefers system TZPATH,
  so %Z abbreviations come from whichever wins per host and are NOT pinned by uv.lock.
  Ruling: accept. CET/JST are stable; a mismatch would show a wrong abbreviation, not a crash.
  Cost if wrong: odelly and CI could print different zone abbreviations for an exotic zone.
Task 4: Ruling: PROMOTE reviewer Minor (_panel_boxes extraction) to the fix round. The brief
  requires Task 6's render_ascii to be an additive change, and the weighted split is currently
  inline at render.py:161-169, so Task 6 would duplicate the geometry. Load-bearing for the
  next task. Cost if wrong: one extra small refactor in a round already open.
Task 4: minor (deferred): GUTTER applied to the last panel, so cols 294-295 are dead paper.
Task 4: minor (deferred): max_primary unvalidated; a large value can overprint the attribution.
Task 4: minor (deferred): a line that does not fit vertically is skipped without advancing y,
  so a later smaller line takes its slot and the recipe's declared order silently changes.
Task 4: minor (deferred): _expand swallows ValueError on a malformed template; validating in
  Panel.__post_init__ would surface a typo at recipe-load time instead of as a missing line.
Task 4: minor (deferred): _percent regex mis-reads grouped/locale figures; "-" anywhere means
  negative. Safe against today's _money only.
Task 4: minor (deferred): the determinism test compares two in-process renders and cannot fail;
  a committed digest of pack_screen(render(...)) would catch a Pillow/FreeType/tzdata change.
Task 4: minor (deferred): stale longer than readings is silently truncated.
Task 4: minor (deferred): from_json raises TypeError on an unknown panel key, not ValueError.
Task 4: minor (deferred): _fit_size computed when line is None; imports inside test bodies.
Task 4: fix round 1/5 dispatched — 3 Important + 1 promoted, plus the env override.
Task 4: fix round 1/5 (4 addressed, 0 open; commits 86240e7..6c43ae0). 70 passing.
  Re-reviewer confirmed: "change"/"previous_close" no longer appear in render.py at all;
  derive is generic (test uses key names `delta`/`base`); the info["text"] hook is fully gone;
  the clip fixture uses the SAME font object and the panel's own canvas width, so "fits" means
  the same thing in the test and the renderer; and _panel_boxes is actually USED by render,
  with the inline arithmetic deleted.
  Mutation question answered YES by reasoning: a 400-char primary exceeds 184px even at the
  minimum font size, so loosening the width check fails both new tests.
Task 4: minor (deferred): a `derive` name colliding with label/value/extra/time silently
  overwrites that field.
Task 4: minor (deferred): some tests rebind the `drawn` fixture name to a string; style smell.
Task 4: complete (commits 5d784a6..6c43ae0, review clean)
Task 4: controller rendered the fixture recipe to verify by eye — 296x128, mode 1, payload
  4742/4742 exact. Vertical rule at ~62% of width, matching layout C. PNG sent to Christoph.
  Observed: the primary figure is capped at 34px (tests/recipes.py) because 40px pushed the
  time line off the panel — visibly smaller than the approved mockup. Recorded for the final
  review as a visual-tuning item, not a defect.
Task 5: BASE=6c43ae0, implementer dispatched (sonnet).
Task 5: implementer DONE_WITH_CONCERNS (commit cb995f3, 108/108 passing)
Task 5: Ruling: the filterwarnings suppression of StarletteDeprecationWarning was REJECTED and
  fixed at source — httpx2 2.16.0 added as a dev dep, filter deleted (commit 9e57ecb). Matches
  Christoph's standing no-warnings rule and the firmware side's CI gate.
  Provenance verified independently (by me AND by Christoph): PyPI says
  home/source = github.com/pydantic/httpx2, requires httpcore2==2.16.0, 22 releases, uploaded
  2026-10-21. Pydantic's org, not a typosquat on the httpx name.
Task 5: Christoph directive — "Zieh den Umstieg durch": complete the migration, not just the
  dev dep. sources.py still imports httpx (runtime dep at pyproject:5).
  RISK he named and I confirmed: FETCH_ERRORS = (httpx.HTTPError, ...) at sources.py:147. If
  httpx2's exception hierarchy differs, that tuple silently stops catching transport errors and
  the fallback breaks quietly — the exact failure this module exists to prevent. Covered by the
  existing timeout-falls-back tests, so a hierarchy change should fail loudly.
  Ruling: queue the migration into Task 5's fix round rather than dispatching now — a second
  implementer over the same files while the reviewer is reading would invalidate the review.
  Cost if wrong: the migration lands one round later than it could have.
Task 5: Ruling: Store.propose(recipe) accepted as scope addition — the brief had no way to
  create an unapproved recipe and Task 6 needs is_approved() for "awaiting approval".
  CROSS-TASK CONTRACT for Task 6: pending_recipe() returns the recipe being previewed whether
  or not approved; use is_approved() to decide the "awaiting approval" wording.
Task 5: Ruling: last-good-readings in approve() accepted. Without it the is_stale flag is
  unobservable, since the "—" placeholder never shows an age.
Task 5: Ruling: malformed config.json -> 500 accepted, over guessing a cadence. The firmware's
  60s retry is the backstop.
Task 5: minor (deferred): telemetry log has no rotation.
Task 5: minor (deferred): app.py reads the store's private _clock.
Task 5: review — APPROVED. 0 Critical, 0 Important, 5 Minor. Reviewer verified every protocol
  constraint with a hardware failure mode, by path not by happy case:
   - identity in headers with an empty body (app.py:48), and a test asserting neither value
     appears in r.text — the assertion that actually catches a regression to JSON
   - 410 is the ONLY rejection branch (app.py:54-56); no 401/403/404 path exists; a missing
     secret becomes "" via Header(default="") rather than FastAPI's 422
   - X-ESPAPER-COMMAND unreachable: the only headers constructed anywhere are the two sleep
     and two registration headers; no middleware, no OTA route
   - 4742 bytes structurally guaranteed via pack_screen's own validation; test also asserts
     content[1] == 1 (bitsPerPixel), since right length + wrong depth is the spec's warned case
   - fallback rendered once in create_app; proved by monkeypatching render to RAISE after
     startup and asserting identical bytes still return
   - cadence re-read from config.json per request (no restart, no reflash)
   - secrets.token_urlsafe(32), stored only as SHA-256, compared with hmac.compare_digest;
     a test greps every file under root for the plaintext
   - stale= verified end to end: store.py:139 -> render.py:161,167,172 -> :80
   - no warnings suppression remains anywhere (whole pyproject.toml hunk inspected)
Task 5: Ruling: PROMOTE two Minors into the fix round.
  (a) put_payload accepts any length (store.py:117-118). Tasks 7/8 call it DIRECTLY, so the
      4742 invariant stops being incidental at that point. One line at the only write point
      makes it structural. Cost if wrong: trivial.
  (b) a corrupt device record raises out of authenticate (store.py:103) -> 500, so the device
      retries forever WITHOUT clearing its identity — the exact permanent stranding the 410
      rule exists to prevent, recoverable only by physically reflashing. Cost if wrong: a rare
      but unrecoverable-in-software device state.
Task 5: minor (deferred): `timezone` param shadows the datetime.timezone import (store.py:87,92).
Task 5: minor (deferred): two panels sharing one source spec are fetched twice during approve.
Task 5: NOTE FOR TASK 6 (from the reviewer): approve() discards the rendered Image and keeps
  only packed bytes (store.py:139), so Task 6's pinned test `pack_screen(png) == screen bytes`
  forces an `unpack_screen` rather than a re-render — re-rendering would use a fresh `now` and
  fresh readings and could never match. Expect unpack_screen to appear in Task 6.
Task 5: NOTE: no config.json or example is shipped, so a default deployment runs on
  DEFAULT_SLEEP_SECONDS = 3600 (store.py:31). Satisfies "configurable", but the cadence knob is
  undiscoverable until documented. Flag for Task 10 (docs).
Task 5: fix round 1/5 dispatched — httpx2 migration + promoted (a) and (b).
Task 5: fix round 1/5 (3 addressed, 0 open; commits 9e57ecb..02b2eff). 115 passing, no warnings.
  The httpx2 hazard MATERIALISED during the fix and was caught: moving the tests to httpx2
  exception classes while FETCH_ERRORS still named httpx.HTTPError failed 2 of the 8 RED tests
  (the approve tests) — the exact silent mismatch Christoph and I both flagged. Task 3's
  boundary tests are what noticed.
  Hierarchy now pinned by a REAL test: httpx2.get against a closed loopback port yields a
  genuine ConnectError, and Response(503).raise_for_status() a genuine HTTPStatusError, both
  asserted against FETCH_ERRORS. Loopback only — nothing leaves the machine.
Task 5: controller RESOLVED both reviewer ⚠️ items (it could not see untouched files):
  - grep for non-httpx2 `httpx` across *.py and *.toml -> zero hits. Migration complete.
  - approve() calls self.put_payload() (store.py:148), so the PAYLOAD_SIZE guard IS at the
    only write point and the invariant is structural, not incidental.
  - full suite re-run by me: 115 passed, no warnings section.
Task 5: minor (deferred): the corrupt-record catch logs nothing, so a damaged device file is
  invisible to the operator. A logging.warning would fit the non-silent-failure goal.
Task 5: minor (deferred): the corrupt-record try also wraps compare_digest, so a TypeError
  from _hash itself would be swallowed as "unknown device".
Task 5: complete (commits 6c43ae0..02b2eff, review clean)
Task 6: BASE=02b2eff, implementer dispatched (sonnet). Carries the shipped-recipe ruling from
  Task 4's ⚠️ and the unpack_screen note from Task 5's review.

## Task 9 pre-flight (done while Task 6 ran)

platformio/native 1.2.1 IS available, so the `[env:native]` route is viable on arm64 macOS.

But EspaperParser is more coupled than ruling R4 assumed. Its includes are:
    Arduino.h, WiFiClientSecure.h, MiniGrafx.h, MiniGrafxFonts.h
So a native build needs FOUR shims, not two — the parser calls gfx->drawPalettedBitmapFromFile
and draws error text, so it is coupled to MiniGrafx as well as to the socket.

Ruling (revises R4): shim MiniGrafx as a NO-OP stub that records calls. The e2e tier exists to
prove HTTP, header parsing, dissectUrl and payload download against a live server — not to
prove drawing, which Tasks 1/4/7 already cover at the pixel level. A recording stub keeps the
real EspaperParser code under test without dragging the graphics stack onto the host.
Cost if wrong: the native tier proves less about the draw path than a full build would; that
path is already covered by the packer round-trip and the parity decoder.

If even that proves too costly, R4's original fallback stands: extract dissectUrl and the
header parsing into a header-only unit, test THAT natively, and cover the socket path via
Task 8's fake device.
Task 6: review — APPROVED. 0 Critical, 0 Important, 7 Minor. Reviewer confirmed the preview is
  structurally unable to drift: single choke point served_screen() = unpack_screen(stored
  bytes), no render/approve call on any preview path; unpack_screen is a strict inverse
  (rejects wrong length/version/depth); the all-white ASCII test genuinely pins polarity
  (reversing the ramp makes white render "@" and the test fails); shipped recipe meets 60/40,
  attribution, Europe/Berlin and units.
Task 6: complete (commits 02b2eff..6b65d18, review clean). 134 tests passing, 0 warnings.
Task 6: minor (deferred): the "matches the device payload" test cannot tell unpack from
  re-render (fixed clock + fixed READINGS); store a hand-drawn payload to make it discriminating.
Task 6: minor (deferred): stale/missing rendered_at shows "Nothing rendered yet" with a screen
  present; render time formatted in the pending recipe's zone, not the render's.
Task 6: minor (deferred): render_ascii rows round to 0 for very small cols.
Task 6: minor (deferred): `store.current_payload() or waiting` duplicated in two routes.
Task 6: minor (deferred): imports inside test bodies; unpack rejection omits w/h mismatch.
Task 6: minor (deferred): shipped recipe hard-codes Berlin (52.52,13.41) + title "Berlin".
Task 6: minor (deferred): pending_recipe()/ZoneInfo unguarded in /preview -> 500 on corrupt json.

## Goal status (device half) — BLOCKED ON HARDWARE

Server half DONE: http://192.168.178.43:8411/preview (LAN-bound, 200), /preview.png,
/preview.txt, screen approved, 4742 bytes, ASCII art delivered to Christoph.

Device half blocked. Sequence of established facts:
  - esptool --before default-reset CONNECTED to the running device, which REVERSES my earlier
    "DTR/RTS are not wired" conclusion. Flashing needs no buttons.
  - DEV build (SERVER_URL -> http://192.168.178.43:8411, plain HTTP) flashed, Hash verified.
  - Since that flash the device answers NOTHING: 115200 silent, 74880 silent, esptool run
    fails, flash-id fails, with hupcl cleared and both control lines explicitly released.
  - The CP2102 still enumerates, so the programmer is fine; it is the ESP side that is silent.
  - Identical symptom to this morning, which turned out to be the device's POWER SWITCH.
Ruling: stop retrying. Asked Christoph to power-cycle and tap RST. Continuing with Tasks 7-11,
which need no hardware, rather than burning turns on an unresponsive board.
Task 7: BASE=6b65d18, implementer dispatched (sonnet).
Task 7: implementer DONE_WITH_CONCERNS (d0f388b), review Needs fixes (1 Important), fix round
  1/5 (3 addressed, 0 open; commits debeacd..38c5053). 138 passing, 0 warnings.
  Reviewer verified the decoder construct-for-construct against MiniGrafx.cpp:1011-1077 —
  refill test, stale buf[0] reuse, shift arithmetic, per-row bitCounter reset — and confirmed
  it reads as a transcription, not a paraphrase. Decoder file untouched by the fix.
  THE FINDING THAT MATTERED: the round-trip compared pixel lists only, and because the decoder
  faithfully reuses the last byte on short input AND the render has white margins, truncations
  of 1, 10, 37 and 148 bytes ALL decoded pixel-identical. Four sizes, all invisible. Fixed by
  asserting len == 6+128*37 and size == (296,128) with literals written out, NOT imported —
  importing the constants would rebuild the circularity the task exists to break.
Task 7: Ruling: pinned pillow>=13 (pyproject listed bare "pillow"; only uv.lock held 13.0.0,
  and get_flattened_data needs a recent Pillow). Cost if wrong: none observed.
Task 7: minor (deferred): the truncation test's sensitivity depends on the render's tail byte
  being white; the length check fires first so it stays correct, but the reasoning is fragile.
Task 7: minor (deferred): pytest.raises(AssertionError) would accept an AssertionError from
  anywhere inside the helper.
Task 7: complete (commits 6b65d18..38c5053, review clean)
Task 8: BASE=38c5053, implementer dispatched (sonnet).
Task 8: fix round 1/5 (2 addressed) then round 2/5 (1 addressed; commits 2c4bbe0..2f4c189).
  146 passing, 0 warnings, 5 consecutive clean runs.
  Round 1 RED: `assert 3600 == 60` twice — the fake returned the server's hourly cadence where
  the firmware returns 60 after a registering boot (registerDevice DISCARDS the screen response,
  so setup()'s initial sleepSeconds=60 survives and the 600s tolerance check falls back to it).
  Also added the 5 optionalHeaderFields the firmware sends on every screen request.
  Round 2 found the MIRROR bug: nothing pinned the server schedule on an ordinary wake, so an
  overcorrection returning 60 everywhere would pass the whole suite — including both tests that
  pin 60. RED proved the new assertion discriminates: `assert 60 == 3600` failed while the two
  60s tests still passed.
Task 8: minor (deferred): 60s retry after a non-410 error implemented but untested.
Task 8: minor (deferred): sleep-until path untested against a moving clock (frozen test clock).
Task 8: minor (deferred): no wrong-secret test; no X-ESPAPER-COMMAND: UPDATE modelling; the
  410 path has no loop guard by design; the fake does not draw the "unknown to server" text.
Task 8: complete (commits 38c5053..2f4c189, review clean)

## Device status after Christoph repowered (22:07)

STILL SILENT. Matrix run: {default-reset, no-reset} x {115200, 74880, 9600} -> no connection
on any combination. 10s passive listen at 74880 -> 0 bytes. The CP2102 still enumerates.
The repower did NOT fix it, which RULES OUT my leading theory (the power switch).
Reasoning recorded: the ROM bootloader always answers after a hardware reset regardless of the
application, so esptool failing on every reset mode means the chip is not being reset or not
powered — i.e. the fault is between the programmer and the board, not in the flashed image.
Most likely the programmer was unseated/reversed during the physical repower; a reversed
programmer still enumerates on USB while the UART and power go nowhere, which is exactly this
symptom and a failure mode already hit once today.
Task 9: BASE=2f4c189, implementer dispatched (sonnet).
Task 9: full-shim route taken (no fallback). Real EspaperParser.cpp compiled native and run
  against a live server. 9/9 native + 146 Python, 0 warnings. Fix round 1/5 (3 addressed).
Task 9: *** A CORRECTION TO ME, NOT TO THE CODE ***
  I wrote into the design spec — and repeated to several subagents — that dissectUrl yields an
  EMPTY HOST for a path-less URL. That is FALSE. Arduino's String::substring takes UNSIGNED
  arguments, so substring(0, -1) from a failed indexOf wraps, clamps and means "to the end".
  Re-reviewer traced it: "http://odelly.fritz.box:8080" -> host "odelly.fritz.box", port 8080,
  path "". The empty host was an artifact of the Task 9 shim clamping negatives to zero.
  A test double created a false belief about the firmware, which I then wrote into a spec as
  fact. Fixing the shim revealed the firmware was never wrong; the document was.
  Spec corrected in c2d88a9 with the error attributed. The practical guidance survives for a
  DIFFERENT reason: always concatenate a path, because an empty PATH makes a malformed request
  line — not because the host would be empty.
Task 9: Ruling: accept `default_envs = native`. PlatformIO cannot exclude a root test suite
  per-environment (the implementer tried *, **, test_* and a filter). Side effect: a bare
  `pio run` now builds only native instead of all 13 device envs. Re-reviewer checked every
  caller — scripts/dev.sh:50-52 and ci.yml:60,81 all pass -e explicitly — so nothing in the
  repo breaks. Cost if wrong: someone running a bare `pio run` by hand gets the host env, which
  is surprising in a firmware repo. Recorded for the final review.
Task 9: FIRMWARE DEFECTS FOUND, routed to the firmware plan, NOT fixed here (EspaperClient/ is
  a fork; local changes must stay reviewable against upstream):
   - EspaperParser.cpp:118 and :334 — `if (!client->available() == 0)`, an inverted check that
     logs "disconnected" when data IS available. Produces 2 warnings in the host build.
   - :378 — %d with a long. Correct on the 32-bit device, a width mismatch on a 64-bit host.
   - :427 — an ENUM passed to %s. On the device this dereferences a small integer as a pointer.
     It sits in the default: arm of the OTA switch, so it fires only on an unexpected update
     return — during a firmware update, in the path you rely on to say what went wrong.
     Worth offering upstream to ThingPulse.
Task 9: minor (deferred): registration test does not assert the id round-trips; fscanf has no
  timeout; `#define private public`; unclosed FILE*; the two :118/:334 warnings remain visible
  in the host build by design.
Task 9: complete (commits 2f4c189..c2d88a9, review clean)
Tasks 10+11: BASE=c2d88a9, dispatched together (docs + CI are the two finishing tasks and the
  docs describe the gate the CI wires).

## Final whole-branch review + fix wave

Final review (opus, 4 passes, 270 KB): "Ready with fixes" — 0 Critical, 6 Important.
It RAN things rather than reasoning: truncated screen.bin, hand-drew a payload, ran `pio run`.
Confirmed the architecture holds by grep — weather|stock|nvda|quote|temperature|meteo|yahoo
across render.py, packer.py, recipe.py, app.py hits COMMENTS ONLY.
Fix wave: all 7 applied in one dispatch (6098198, cc6801a, efe05e4, eef7a10, fa7d263, 5b0b7c7).
172 Python + 9 native tests, GATE PASSED (5 of 5). Re-review: all addressed, blockers closed.

Ruling: `default_envs = native` REVERTED to Espaper29Bw-PROD. My earlier ruling recorded the
  side effect as "surprising"; the final reviewer ran it and found it BROKEN — a bare `pio run`
  died with undefined `_main`, because the native env compiles only EspaperParser.cpp with no
  main and no board stubs. I was wrong; `pio test -e native` stays mandatory instead.

Task 9 ⚠️ resolved by me: EspaperClient/settings.h SERVER_URL is bar's DHCP address. Ruling:
  leave the value, add a PROVISIONAL comment naming spec decisions 1 and 13 and the cost of
  getting it wrong (error screen, 60 s retry loop, physical reflash). A comment-only change
  keeps the fork reviewable against upstream. Cost if wrong: someone flashes without reading.

Task 10/11 parked: `_parse` does not guard current["weather_code"]; a null renders the literal
  "None" in the description line — same "confident non-value" class as Fix 1, secondary line.
  Ruling: parked. Real, not a regression, and the process allows no second fix wave.
Task 10/11 parked: a non-dict `current` or `daily` raises TypeError outside FETCH_ERRORS and
  escapes approve(). Ruling: parked. Exotic input; those key shapes were never validated.
  Both worth a follow-up ticket.

## Firmware plan — Tasks 1-5, 7 executed (Tasks 6, 8 held)

Executed autonomously while the board was dark, to avoid idling. All verified on BOTH tiers:
`pio test -e native` and the containerised Xtensa build (the only proof the firmware compiles,
since the toolchain is x86-only on this arm64 Mac).

Task 1  three upstream defects fixed (ae6c2d2). Fork is CURRENT with upstream master
        (6703a31, 2025-06-10); all three still present there; no upstream issue or PR exists.
        Implementer CORRECTED ME: the :118/:334 fix is not behaviour-neutral as I claimed —
        the "Client disconnected" log fired when data WAS available. Behaviour-corrective.
Task 2  SERVER_URL is a stored setting (70a86b0). PROVISIONAL block removed from settings.h.
        Controller closed its verification gap via the container build: +80 B RAM, 0 warnings.
Task 3  stored-URL validation (499cc3b). NO extra request — reinterprets the existing fetch.
        Both mutation checks bit. +68 B RAM, +484 B flash.
Task 4  mDNS discovery (169b2a7), exception path only. +600 B RAM, +23594 B flash.
        BEST FINDING OF THE PLAN: Task 3's no-extra-work test would have passed for the WRONG
        REASON, because it counts TCP connects and mDNS is UDP. The implementer noticed its own
        change had silently voided an existing guard and added MDNS.queryCount == 0.
Task 5  server-side advertisement (25140e6), python-zeroconf, off by default, degrades to
        serving normally when unavailable. 177 Python tests.
Task 7  410 reboot-loop guard (5f7931a). RED was `RebootLoop: 20 boots in a row without a
        sleep`. CONSECUTIVE_GONE counter beside TOTAL_DEVICE_STARTS; one extra flash write on
        the 410 path only. The FAKE DEVICE drifted on purpose — its old wake() hid the loop by
        deferring a second 410 to the next wake. Second time this fake was corrected TOWARD the
        firmware. +12 B RAM, +244 B flash. 180 Python + 35 native.

Ruling: SERVER_URL_SOURCE added (manual | discovered); discovery never overwrites `manual`,
  permanently. Someone typing an address is exercising control, usually while debugging;
  silently overriding that is the behaviour people hate most in auto-configuring systems.
Ruling: a rejected `manual` URL skips discovery entirely and draws the failure screen, rather
  than falling back to a discovered server for that wake. Same reasoning. One-line to reverse.
Ruling: STOPPED after Task 7. Task 6 (OTA) publishes GitHub releases — outward-facing, the
  owner's call. Task 8 is bench verification and needs the hardware.

Deferred: a down server now costs a WiFi reconnect + 1.5 s query per 1-minute retry, and the
  failure path does TWO e-ink refreshes (the parser draws its own generic error before ours).
  E-ink refreshes are slow and wear the panel. Worth suppressing the generic one.
Deferred: registerDevice is not routed through the Task 3 verdict.
Deferred: a large 200 from a non-ESPaper host is written to LittleFS before it is judged.
Deferred: ESPAPER_ADVERTISE_PORT must be hand-matched to uvicorn's --port.
Deferred: discovery has NEVER run against a real mDNS stack; WiFi is off after the first fetch
  (the parser passes sleepWifi as its post-download callback) and the .ino now reconnects
  before discovery — untestable in every tier we have. Likeliest thing to need device debugging.
