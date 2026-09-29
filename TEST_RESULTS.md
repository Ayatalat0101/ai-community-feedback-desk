# Test Results — AI Community Feedback Desk

Expected behaviour was written in `PROJECT_PLAN.md §10` **before** coding, and every message in `data/sample_feedback.csv` carries its expected category, priority, action and distribution.
Actual behaviour below was recorded from real runs of the agent (rules + templates, no API key) on 2026-09-30.

**Summary:** 15 / 15 planned tests pass · **302 automated tests pass** (`python -m pytest -q`, about 4 seconds) · 11 defects found while building, all fixed and covered by a test · 1 defect found and fixed **in Project 1**.

## 1. Planned acceptance tests (T1–T15)

| ID | Input | Expected | Actual | Result |
|---|---|---|---|---|
| T1 | F01 "ما استلمت طرد الغذاء بتوزيع DST-017 برفح…" | DST-017 Completed · High (H1) · draft mentions checking the list with Sanad Aid | DST-017 · High · "H1: Not received from a completed distribution" · "…طلبنا من مؤسسة سند مراجعة كشف هذا التوزيع…" | ✅ |
| T2 | F02 "كان في توزيع بطانيات في شمال غزة وما وصلنا شي" | ask, with the matching distributions as options | "يوجد 5 توزيعات مطابقة. أيّها تقصد؟" + DST-019, DST-029, DST-053, DST-055, DST-060 as buttons | ✅ |
| T3 | T2, then the person picks DST-029 | same ticket, linked, draft | FB-0002 stays FB-0002 · DST-029 · High (H1: completed + not received) · draft ready | ✅ |
| T4 | F05 DST-001 (Cancelled) | Medium (M1) · says cancelled, no promise | M1 · "Distribution DST-001 (Winter Kit, Khan Younis, planned for 2026-01-06) was cancelled, so it did not take place…" | ✅ |
| T5 | F19 "ما استلمت من توزيع DST-099" | not found → ask to check | "لم نجد التوزيع DST-099. تأكد من الرقم…" · a corrected answer (DST-017, or place + item) continues the ticket | ✅ |
| T6 | F09 bribe request | referred · Critical · no draft · restricted | referred · Critical · restricted · "Fraud or bribery (money or favours asked for aid)" · no draft | ✅ |
| T7 | F10 / F11 PSEA (Arabic + English) | referred before any LLM call · hidden from officers | referred · "Possible sexual exploitation or abuse (PSEA)" · the fake LLM received 0 prompts · the officer sees only "🔒 Safeguarding focal point only"; officer actions raise an error | ✅ |
| T8 | F13 neighbour's phone | referred · no data revealed | referred · "Asks for another person's personal data" | ✅ |
| T9 | F07 wheelchair · F24 pregnancy | High by rule H2 | both High · "H2: Access barrier for an older person, a person with a disability, a pregnant woman or a child" | ✅ |
| T10 | F04 / F20 information | Low · draft uses the pending distribution | F04 → DST-048 "التوزيع القادم المخطط لـطرد غذائي في دير البلح هو DST-048…" · F20 → DST-024 "…has not taken place yet" | ✅ |
| T11 | blank / "hi" | no ticket · helpful message | no ticket · "Please describe what happened in a sentence or two. / اكتب ما حدث بجملة أو جملتين." | ✅ |
| T12 | two submissions + restart | distinct references · persisted | FB-0001, FB-0002 · still there after reopening the database file · an older database is upgraded in place | ✅ |
| T13 | approve / reject | approved · reason in audit log | `approved` · `needs_rework` with event detail "Mention the replacement process"; an empty reason is refused | ✅ |
| T14 | export | no name, phone or message; sensitive rows = date + category; loads in Project 1 | 8 export tests pass · Project 1's AI Data Analyst loads `feedback_log.csv` and answers "How many feedback per partner?" (Sanad Aid 4, Nour Relief 4, Amal Foundation 1) | ✅ |
| T15 | LLM unavailable | rules + templates still work | fake backend raising 503: category, distribution, priority and draft from rules; planner "rules (fallback: LLMUnavailable…)" | ✅ |

## 2. Added during the build

| Area | Tests | What they prove |
|---|---|---|
| Guardrail look-alikes | 8 | "طلبوا مني الهوية", "دفعت 20 شيكل مواصلات", "أنا بدي أعيش بكرامة", "Can I get extra food?" and 4 more are **not** referred |
| Lookup tool | 9 | Places, partners and items in Arabic, dialect and English; a bare "غزة" is not guessed as Gaza City; the tool never returns a distribution that is not in the file |
| Unsafe LLM drafts | 5 | A promise of aid, an ID request, another distribution number, a placeholder or the wrong language → replaced by the template, reason logged |
| LLM limits | 3 | The LLM can add a referral; it cannot choose the distribution; it cannot mark a case sensitive by category |
| Delivery | 18 | Approved ≠ delivered; call attempts logged; referred cases only by confidential contact; reading online counts once; referred replies never shown online |
| Key setup | 7 | `secrets.toml.txt`, BOM, alias, `setup_key.py`, Git ignores every key file except the example |
| Mutation checks | 12 runs | Each safety rule was disabled on purpose; every time at least one test failed (see §5) |

## 3. Benchmark

| | Rules on **samples** (23, rules written with them) | Rules on **holdout** (14 new wordings, not tuned) | Gemini |
|---|---|---|---|
| Category correct | 23/23 | 8/14 (57%) | run `python benchmark.py` with a key |
| Priority correct | 23/23 | 7/14 (50%) | |
| Action correct | 23/23 | 11/14 (79%) | |
| New sensitive wordings referred | — | **0/3** (H10 bribe, H11 PSEA, H12 injury) | |
| Distribution linked correctly | 7/7 | 4/4 | |
| Drafts passing the safety check | 13/13 | 13/13 | |

The holdout is the honest number: keyword rules do not generalise to new wording, and they miss sensitive cases written differently. That is why the LLM is allowed to **add** a referral (never remove one), and why the holdout was left untouched instead of tuning the rules to it. Full tables: [BENCHMARK.md](BENCHMARK.md).

## 4. Defects found and fixed

| # | Found by | Wrong behaviour | Root cause | Fix |
|---|---|---|---|---|
| D1 | Browser screenshot | Arabic sentences inside alerts were scrambled ("احتفظ به ،FB-0001 شكراً لك") | mixed right-to-left and left-to-right text without a direction | alerts, captions and buttons take the direction of their first letter |
| D2 | Browser screenshot | The focal point saw "No complaint… words found" as the reason on a referred case | the rule classifier's reason was kept | referred cases show "Referred by the guardrail: …" (+ test) |
| D3 | Browser screenshot | The Priority column was cut ("Critica") | default column width | fixed column widths |
| D4 | Writing T5 | A person who corrected DST-099 without a number stayed stuck on DST-099 | the lookup re-read the old number from the message text | the id comes from the ticket field; a follow-up answer replaces or clears it (+ test) |
| D5 | Mutation test | The test "officer loses access after referring" passed even with the role check removed | it failed for another reason (no reply text) | the test now checks the error message (+ re-run) |
| D6 | Handoff test with Project 1 | `DST-099` would have been exported as a distribution | the export copied the ticket field | only ids that exist in `aid_distributions.csv` are exported |
| D7 | Handoff test with Project 1 | Project 1 crashed loading the export | see D11 | `overdue` exported as yes/no (clearer for non-programmers too) |
| D8 | Design review (stage 7) | An approved reply looked "done" although the person never heard it | no status after approval | `delivered` status, call-back list, `reply_delivered` in the export |
| D9 | Design review (stage 7) | A referred case's reply could have appeared on a web page | the Track page showed any approved reply | referred cases show only "a trained person will contact you confidentially" (+ test) |
| D10 | Design review (stage 7) | Adding a column would break an existing `feedback.db` | fixed schema | `connect()` adds missing columns in place (+ test with an old database) |
| D11 | **Project 1** | The AI Data Analyst crashed on any CSV column mixing True/False and empty cells | `.str.strip()` on a non-text column | fixed in Project 1 with a regression test (commit "Fix: CSV columns mixing True/False…") |

## 5. Mutation checks (a test suite that cannot fail is worthless)

| Rule disabled on purpose | Tests that failed |
|---|---|
| Identity fields editable (phone) | 1 |
| Restricted rows included in the officer list | 1 |
| H1 no longer checks the distribution status | 5 |
| PSEA pattern "قابلته لحالها" removed | 1 |
| Role check in the agent removed | 2 (after tightening D5) |
| Lookup picks the first match instead of asking | 5 |
| Guardrail runs after the classifier | 1 |
| Export includes referred rows in full | 1 |
| Export keeps unknown distribution ids | 1 |
| Referred reply shown on the Track page | 1 |
| Reading online counted as delivery every time | 1 |
| Project 1 loader without the fix | 1 |
