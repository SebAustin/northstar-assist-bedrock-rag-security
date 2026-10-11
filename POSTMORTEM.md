# POSTMORTEM: Northstar Assist capstone

Blameless. It describes mechanisms and process gaps, not people. Sources: git history (27 commits, tags s0 to s6), `STATUS.md`, `ASSUMPTIONS.md` (A1 to A19), `PLAN.md` (section 7, R1 to R7), `deliverables/04` to `07`, `tests/`. Incidents 1 to 8 were supplied by the project owner; items marked "verified" were checked in the repo.

## 1. Outcome in five lines

1. A RAG agent (Harness, Gateway, Managed Knowledge Base, S3) was deployed in a temporary lab account, hardened, and validated. All 7 rubric deliverables were written and exported to Word and PDF.
2. The hardened red-team suite passed 72 of 72 runs (24 cases, 3 runs each). The unguarded baseline passed 45 of 69.
3. Launch verdict: approve with conditions. The main open risk is indirect injection, because retrieved text is not screened by any guardrail policy.
4. Least-privilege IAM, a guardrail enforced by an IAM condition, 11 metric filters, 4 alarms, and a live containment drill all have evidence in `evidence/`.
5. Teardown has not run. The lab session expired first, so it needs a new session and refreshed keys (A19).

## 2. Timeline by slice

| Slice | Tag | What happened |
|---|---|---|
| Plan loop | none | Plan critic: 13 defects in iteration 1, PASS 91/100 in iteration 2, then 7 revisions (R1 to R7) merged as section 7. |
| S0 Scaffold, preflight | s0-scaffold | Starter files copied read-only, account guard in `infra/lib.sh`, preflight probe of lab permissions. |
| S1 Baseline | s1-baseline | Bucket, Managed KB (30 of 30 documents), gateway, harness. The console hung while creating the harness (A11), so it was created from the CLI. |
| S2 ML-BOM, STRIDE-ML | none | Template filler built test-first; threats added from observed console behaviour (A15). |
| S3 Guardrail | s3-guardrail | Guardrail v1 over-blocked, v2 replaced it. Lockdown guardrail needed a second fix. Live stop reason differed from the documented one (incident 2). |
| S4 IAM | s4-iam | Three roles scoped, 35-check simulation before and after, live bypass probes denied. Rollback failed once (incident 1). |
| S5 Monitoring | s5-monitoring | Invocation logging, 11 filters, 4 alarms, containment script. Reviewer found two HIGH defects before commit (incident 3). |
| S6 Validation | s6-validation | Hardened suite 72/72, poisoned-document test, containment drill, token alarm retuned, verdict written. |
| S7, S8 | none | Dashboard validated on 128 live log records. Reports exported, teardown script written and run in read-only plan mode only. Lab session expired (incident 7). |

Calendar: planning and scaffold on one evening, S1 to S8 on the next day (commit timestamps, verified). The work was compressed, which raised the cost of each late-found defect.

## 3. What went well

- **Plan critic caught real gaps early.** The R-revisions changed what was built: ZeroRetrieval counted per turn instead of per model call (R1), a guardrail filter fallback (R2), IAM-write permissions added to preflight (R3), and a verdict rule fixed before any result existed (R4). Deliverable 07 applies that rule as written.
- **Preflight before building.** `infra/00_preflight.sh` found permission gaps on day one (no CloudTrail lookup, A14), so no slice was designed around a call the lab denies.
- **Test-first with real fixtures.** `tests/fixtures/` holds real invocation records, including a real output-side block. The test suite grew to 211 tests (STATUS.md) and caught parser bugs in S1 (split tool results) and S3.
- **Evidence before claims.** The before/after IAM simulation, live override probes (denied after hardening), and the metric filters tested with `aws logs test-metric-filter` against real records let each claim point to a file.
- **Independent review paid off.** The S5 reviewer found two HIGH defects that tests written by the builder did not (incident 3).
- **Human gate on cloud changes.** Each cloud-changing slice was approved before it ran. The poisoned document was uploaded, tested, removed and the knowledge base re-synced, with the version trail kept (`evidence/task7/poisoned_doc_versions.json`).
- **Limits were written down.** Each deliverable has a limits section; the assumptions log recorded 19 surprises as they happened.

## 4. What went wrong

### 4.1 Hidden rollback failure produced false "before" evidence (S4)
- **Impact:** The "before" policy simulation held the hardened roles' results. Had it been committed, the before/after comparison, the core evidence of Task 4, would have been meaningless.
- **Caught:** The builder compared the numbers and saw the "before" matched the "after".
- **Root cause:** The rollback ran inside an `&&` chain piped through `tail`; the pipe returned `tail`'s exit status, so the failure was invisible. Second cause: the documented rollback used `iam:SetDefaultPolicyVersion`, which the lab denies, and the preflight did not probe it.
- **Fix:** File deleted, sequence redone one step at a time with exit codes checked. Rollback rewritten to publish the original document as a new version, pruning to stay under five versions (verified in `infra/04_iam_harden.sh`, comment at line 47).

### 4.2 Guardrail rules matched the wrong things (S3)
- **Impact:** A "credentials" denied topic blocked legitimate questions about password policy and API authentication. The "block everything" lockdown let a poem through. The assumed stop reason (`content_filtered`) was wrong; the live value is `guardrail_intervened` for both a block and a masked answer.
- **Caught:** Live probes (20, later 27) and the benign control set.
- **Root cause:** Topic definitions were judged by wording, not tested against benign near-neighbours before attaching. The lockdown was assumed to be absolute. A5 was taken from library documentation and not probed until after code depended on it.
- **Fix:** A regex on the secret's value replaced the topic. A match-anything regex was added to the lockdown, and plan R5 (validate the lockdown, do not assume it) was applied. The parser accepts both stop reasons. Residual (verified): `ASSUMPTIONS.md` A5 still states the wrong value and `tests/` still use `content_filtered` as a fixture value.

### 4.3 Two HIGH defects found in review, and one wrong assumption (S5)
- **Impact:** (a) The playbook's eradication step would have re-attached the main guardrail and ended a lockdown early, in a live incident. (b) The monitoring script reported success while creating no alarms when a JSON definition had a typo. (c) "A block has zero output tokens" was assumed in the metrics.
- **Caught:** The independent reviewer, before commit. Item (c) was confirmed two hours later by a real output-side block (122 tokens written, then withheld).
- **Root cause:** (b) `while read ... done < <(jq ...)` runs zero times when jq fails and `set -e` does not see it. (a) The playbook was reviewed step by step, not as a sequence with state. (c) A behaviour was inferred from one sample.
- **Fix:** Eradication reordered; the script validates definitions before the loop and fails on zero alarms; blocks are classified by the trace action, with the real record kept as a fixture.

### 4.4 A test overwrote uncommitted evidence (S5)
- **Impact:** Four evidence files were replaced by stub output. They were not yet committed, so git could not restore them.
- **Caught:** The builder saw stub values in the files.
- **Root cause:** A test ran a real infra script against a stubbed `aws`, and the script wrote to a hard-coded evidence directory.
- **Fix:** Evidence re-captured from the live account. `NORTHSTAR_EVIDENCE_ROOT` now overrides the path (verified in `infra/lib.sh`, line 16) and tests point it at a temporary directory.

### 4.5 Biased poisoned-document test (S6)
- **Impact:** The user-visible result ("blocked") credited the wrong control. The model had ignored the injected instruction 3 of 3 times; the output guardrail blocked a harmless summary, most likely because of the word "poisoned" in the file name.
- **Caught:** Reading the invocation log, not the suite output.
- **Root cause:** The fixture labelled itself a security test and carried the attack word in its name, so it did not look like a real attack and it tripped an unrelated filter. The pass rule looked only at the final outcome, not at which layer acted.
- **Fix:** Deliverable 07 reports the result under the real mechanism and states the test's limits. Open: repeat with unlabelled documents, ten runs each (condition C5).

### 4.6 Credentials pasted into the chat
- **Impact:** None on the account. Keys in a chat transcript count as exposed.
- **Caught:** At once; the assistant refused to use them.
- **Root cause:** The setup instructions did not say how to give the tooling access without sharing keys.
- **Fix:** The user configured the `udacity` CLI profile and regenerated the keys. `infra/lib.sh` refuses any other profile (A1).

### 4.7 Lab session expired before teardown
- **Impact:** All calls denied minutes after the last evidence was captured. Resources remain until a new session; cost exposure is small but not zero.
- **Root cause:** The plan assumed a recoverable session (section 5) and put teardown last, behind close-out documents.
- **Fix:** A19 recorded; `--plan` mode listed the resources just before expiry.

### 4.8 Lab limits changed the plan repeatedly
Console-only steps, the hung harness form (A11), no CloudTrail (A14), no simulation of custom policies, Marketplace-gated models, and no SNS notification (A17) each caused rework. Preflight covered some and missed others, and the deliverables record each one.

## 5. What was lucky

- The S4 false "before" file was noticed only because the builder read the numbers. No check enforced it.
- The real output-side block appeared two hours after the review that predicted it. Without it, the token-based assumption would have stayed untested.
- The model ignored the injection 3 of 3. A weaker run would have produced a worse, more informative test, but the evidence we have cannot show a 1-in-10 failure.
- The lab session ended after capture finished, not during the drill.
- Stub-overwritten files were regenerable only because the account was still reachable.

## 6. Lessons (concrete practices)

1. **Check every exit code in evidence-producing sequences.** Do not pipe a command whose status matters into `tail`, `head` or `tee` inside `&&`; use `set -o pipefail` or `PIPESTATUS`. Run state-changing steps one at a time and assert the expected state before saving evidence.
2. **A "before" artifact must prove it is a "before".** Record a state identifier (policy version, hash, timestamp) inside the file and assert it differs from the "after".
3. **Probe the exact recovery path, not only the forward path.** Preflight must call the rollback and cleanup APIs (`SetDefaultPolicyVersion`, delete, detach), because lab or production permissions may differ.
4. **Tests must not be able to write to real evidence.** Every script takes an output-root override, and tests set it to a temporary directory. Commit evidence before running new tests that touch the same scripts.
5. **Test controls against benign near-neighbours before attaching them.** Each deny rule gets at least two legitimate questions that share its vocabulary, and each "block all" rule gets a harmless off-topic input.
6. **Verify observed values against the live system before coding on them.** Stop reasons, log field names and token behaviour were assumed from documentation or one sample. Capture one real record per class, store it as a fixture, then write the parser.
7. **Make attack fixtures neutral, and attribute results to a layer.** Name and word test documents like real ones, and report which control acted from the trace, not from the final status.
8. **In shell loops over generated input, fail on empty.** Loops fed by process substitution hide upstream failure; validate the input and assert a non-zero count before reporting success.

## 7. Project-specific notes (stay here)

- The harness form hung, and the CLI creation reused the console-created role (A11). This is specific to the lab console.
- Alarms have no notification target (A17). The tester cannot subscribe an address in the lab.
- Open conditions C1 to C5 in deliverable 07 (invoker restriction, retrieved-text screening, per-user identity) are product decisions, not workflow lessons.
- Teardown to run next session: `infra/99_teardown.sh`, after the owner confirms evidence is complete.
