# MVP validation record

Environment: Windows, Python 3.14.5. Dependencies installed into the project `.venv`, with the installed versions captured in `requirements-lock.txt`.

Automated suite (2026-09-18): **87 tests passed**. JavaScript syntax checks passed for app.js and guided.js. Two existing Starlette/AnyIO deprecation warnings remain. Earlier `pip check` reported no broken requirements. Automated checks cover:

- Personal lab UI: browser checked the overview and circuit view switching. Synthetic localhost fixture verified start, reload/reconnect to the same job, cancel, manual resume, and automatic navigation to saved BOM with no cloud AI call.
- Cancellation kills only the owned subprocess, retains completed stages and old circuit, blocks competing edits, releases the job slot, and permits a new job.
- Identical part selection preserves version, evidence, circuit and approvals; failed PDF URLs are skipped until explicitly retried.

- Required fields, rejection of component planning before Requirements approval.
- Offline MCU draft generation, BOM and signal connection exports, unresolved physical pins blocked.
- Approval order, evidence hashes, critical findings, upstream invalidation, withdrawal and restoration.
- Immutable SQLite snapshots, concurrent stale-write rejection, original-file hashes and path safety.
- Datasheet source/page/quote existence, human-only confirmation, endpoint pin/name matching.
- Physical pin assignment, BOM consistency, net conflicts and basic voltage conflicts.
- PDF text extraction with page numbers and scanned/blank PDF limitations.
- BOM aliases, normalized netlist/DRC, unsupported formats, bad ZIP paths and fake Gerber layer signatures.
- Full six-gate workflow using an explicitly synthetic fixture and explicit test approval calls. This tests workflow mechanics, not electronic correctness.
- API project creation, resume, upload preservation, history, ZIP export, schema validation, local request guards and API-key exclusion.
- Compatible-provider request/response contract with mocked HTTP, malformed responses and HTTP errors.
- Codex CLI adapter contract with mocked subprocess, standard `CODEX_HOME` discovery, ephemeral/read-only flags and no credential copying.

Original MVP manual browser smoke test (before the research upgrade):

1. Created “MCU Sensor Board · 4-layer (ตัวอย่าง)”. The initial form asked 11 remaining questions after reading the layer count.
2. Filled the labeled software-test values and saved Requirements.
3. Exercised the approval dialog with the reviewer name “Software UI test — not an engineering approval”.
4. Ran Research → Circuit/BOM → Review and saw 6 BOM items and 12 logical connection rows. No physical pin numbers or footprints were invented.
5. Confirmed the later gates were blocked for missing evidence and voltage/pin information.
6. Opened Review, generated the manufacturing checklist and four bring-up steps, and checked the browser error log (no errors).
7. Stopped and restarted the background server, reloaded the browser and reopened the persisted project.
8. Withdrew the test approval. The delivered example has **0 of 6 gates approved**; the draft and test history remain available.

Live research upgrade validation (2026-09-18):

- Isolated fictional ESP32-C3-MINI-1 / BME280 board; no private user brief sent. Codex model `gpt-5.6-terra`, effort `low`.
- Discovery reported 3 web-search events and returned 7 specific candidate references. Discovery consumed 113,468 input tokens and 3,227 output tokens; this is one measured run, not a per-project cost promise. Search result context can be large, so discovery is reused until explicitly refreshed.
- Downloaded 4 public manufacturer PDFs (Espressif, Bosch, Diodes, Bourns). Three references had vendor HTTP 403 responses; reported as missing documents instead of silently accepted. The shared switch datasheet applies to two references.
- Bosch's publicly readable AES PDF required the `pypdf[crypto]` dependency. Empty-password encrypted PDFs can now be read; password-protected documents remain rejected.
- Retained 28 source/page/quote-checked facts, including 13 pin facts. First circuit attempt rejected an unsupported voltage assertion and saved the successful research plus the failed-call telemetry.
- After adding physical-claim grounding, regenerated only the circuit using retained research: 9 BOM rows, 11 numbered pins, 12 signal connections, 5 with both physical endpoints supported. That circuit call reported 19,651 input / 3,839 output tokens.
- Confirmed that rerunning the same plan needs zero further AI calls and that unverified drafts still cannot pass the component/connection gates.
- Added regression checks for search-event verification, cache reuse, per-stage usage, retaining failed attempts, draft evidence, background progress and duplicate-job protection, public-only download targets, partial download failure, and AES PDF reading.

Verification limits:

- API-compatible provider transport remains tested with mocks. Codex live testing above exercises public documents and a fictional brief; it does not establish electrical correctness or complete coverage of every datasheet page.
- No real PCB is certified. The example is deliberately incomplete and cannot pass the manufacturing gate.
- EasyEDA proprietary shape connectivity, arbitrary netlist/DRC formats, image vision, Gerber geometry, PCB SI/PI and fabrication correctness are outside this MVP.
- The test runner currently emits two deprecation warnings from Starlette/AnyIO; tests still pass. Dependency compatibility was also checked with `pip check`.

Run the reproducible suite with `.venv\Scripts\python.exe -m pytest -q`. See `README.md` for operating steps, data backup, constraints and extension instructions.

Additional UI verification (2026-09-18): opened the real local app and confirmed the existing project, selected model and Requirements approval remain available; inspected the candidate cards, PDF links, BOM, numbered pins and connection table in the separate fictional test instance. Verified the economy preset updates both dropdowns without saving over the user setting. Added a regression for prioritizing the actual pin table over repeated pin mentions and contents pages.

The pin-page selection regression was also exercised with Codex: the ESP32 table on PDF page 11 was included and four MCU pin facts survived source validation. This independent run returned 17 retained facts and a draft with 7 BOM rows, 6 numbered pins and 10 connections (2 with both numbers). Counts vary by AI output; the figures above describe separate runs. The run consumed 35,190 input / 3,175 output tokens for research and 18,289 input / 3,461 output for the circuit. This revealed verbatim-quote and pin-alias omissions; prompts now explicitly require contiguous unedited quotes, one physical pad per fact, and exact pin labels. Those final prompt refinements have schema/regression coverage but have not had another live run.
