# Acceptance: rubric and success criteria against evidence

Criteria and IDs come from `REQUIREMENTS.md`. Status is one of Met, Partly met, Not met. Every path below was checked to exist. Section numbers refer to the deliverable named in the same cell. Exports of each deliverable are in `deliverables/export/`.

## Success criteria

| ID | Criterion | Status | Evidence |
|---|---|---|---|
| SC-1 | Harness answers the smoke prompt with Haiku 4.5 | Met | `deliverables/01_harness_evidence.md` sections 3 and 4; `evidence/task1/smoke_baseline_20261010T192934Z.json`; `evidence/task1/playground_answer.jpg` |
| SC-2 | Answer uses KB content: Retrieve call, chunks, cites `company_policies_handbook.html`, playground trace shown | Met | `deliverables/01_harness_evidence.md` section 4; `evidence/task1/playground_retrieve_trace.jpg`; `evidence/task1/smoke_baseline_20261010T192934Z.json` (5 chunks) |
| SC-3 | KB sync: 0 failed, 30 of 30 indexed | Met | `deliverables/01_harness_evidence.md` section 2; `evidence/task1/kb_sync.jpg`; `evidence/task1/kb_ingestion_jobs.json`; re-check after hardening in `evidence/task4/kb_sync_after_hardening.json` |
| SC-4 | ML-BOM has entries for FM, embedding model, knowledge source, storage and retrieval services, all 3 default IAM roles | Met | `deliverables/ML-BOM.docx` (Model A, Model B, section 4 table: corpus, bucket, KB, vector store, Gateway, Harness, three default roles plus the logging role); source `content/mlbom.yaml` |
| SC-5 | Each entry states type, provider, intended use, limitations and transparency gaps | Met | `deliverables/ML-BOM.docx` (model sections 3.1 to 3.3; section 4 table columns Type, Provider, Limitations; section 5 findings F-01 to F-09) |
| SC-6 | System overview matches deployed `get-harness` / `get-gateway` output | Met | `deliverables/ML-BOM.docx` "System Overview"; `evidence/task2/mlbom_vs_deployed.md` (all 12 deployed values from `evidence/task1/harness.json`, `gateway.json` and `knowledge_base.json` appear in the ML-BOM) |
| SC-7 | STRIDE-ML assets with classification and trust boundaries (user to harness, harness to model, harness to gateway to KB, chunk to model context) | Met | `deliverables/STRIDE-ML.docx` sections 1 and 2 (data assets table; boundaries TB1 to TB5); source `content/stride.yaml` |
| SC-8 | At least 3 prioritised risks (direct injection, indirect injection, data exposure) with likelihood, impact, score, mitigation | Met | `deliverables/STRIDE-ML.docx` "Prioritized Risk Register" (22 threats): E-01 score 16, E-02 score 15, I-01 score 16 |
| SC-9 | At least 2 control types, input and output covered, guardrail attached via `guardrailConfig` | Met | `deliverables/05_safety_controls.md` sections 2 to 5; `guardrail/config.json`; `evidence/task5/harness_after_guardrail.json`; `evidence/task5/guardrail_probes.md` |
| SC-10 | IAM: original and scoped documented; scoped to Haiku 4.5 profile, KB, guardrail, gateway; wildcards justified; simulation shows denials for other models and KBs | Met | `deliverables/04_iam_hardening.md` sections 3 to 6; `iam/before/`; `iam/after/`; `iam/simulation_matrix.json`; `evidence/task4/simulation_before_after.md`; `evidence/task4/override_probe_after_hardening.json` |
| SC-11 | Monitoring plan names logs and metrics, an AI-specific signal and a concrete threshold | Met | `deliverables/06_monitoring_and_ir.md` sections 2 to 4 (for example more than 5 prompt-attack blocks in 1 hour); `evidence/task6/metric_filters.json`; `evidence/task6/invocation_logging_config.json` |
| SC-12 | IR playbook for prompt injection with containment (console path and CLI) and investigation (Logs Insights queries) | Met | `deliverables/06_monitoring_and_ir.md` sections 5 and 7; `monitoring/saved_queries.json`; `infra/ir_contain.sh`; `evidence/task6/ir_drill.jsonl` |
| SC-13 | At least 3 prompts across risk categories with behaviour, guardrail intervention, appropriateness, and a verdict | Met | `deliverables/07_launch_readiness.md` sections 1, 4 (six cases) and 6 (approve with conditions); `evidence/task7/poisoned_invocation_records.json`; `results/matrix_hardened.md` |
| SC-X1 | CloudWatch alarms exist, alarm JSON included, one reaches ALARM on replay | Met | `deliverables/06_monitoring_and_ir.md` section 4; `monitoring/alarms.json`; `evidence/task6/alarms.json`; `evidence/task6/alarm_history_prompt_attack_spike.json`; `evidence/task6/alarm_state.jpg` |
| SC-X2 | 10 or more prompts mapped to OWASP LLM01 to LLM10, expected-vs-actual matrix, 3 runs each | Met | `redteam/prompts.yaml` (24 cases); `results/matrix_hardened.md` (72 runs); `results/matrix_baseline_no_guardrail.md`; `deliverables/07_launch_readiness.md` sections 2 and 3. The matrix is in `results/`, not the `evidence/task7/matrix.md` named in `REQUIREMENTS.md` |
| SC-X3 | Expanded threat model: multi-turn evasion, model extraction, embedding supply chain, scores and mitigations | Met | `deliverables/STRIDE-ML.docx` section 3: T-02 (score 12), I-04 (score 4), T-03 (score 6); DoS and cost in D-01 to D-03. I-04 status is "Planned" |
| SC-X4 | Streamlit page shows intervention rate, token usage, retrieval success; aggregation tests pass; screenshot | Met | `streamlit_app/pages/1_Monitoring.py` (named `monitoring.py` in `REQUIREMENTS.md`); `streamlit_app/monitoring_data.py`; `tools/metrics.py`; `tests/test_metrics.py`, `tests/test_monitoring_data.py`, `tests/test_monitoring_page.py`; `evidence/task7/dashboard_cloudwatch.jpg`; `.venv/bin/pytest -q` gave 211 passed |
| SC-Z | Every SC row maps to an existing file and all NFRs verified | Met, with two caveats | All SC rows above map to existing files; independent verification returned SOLID (92/100). Caveats: NFR-1 rests on an estimate, and NFR-5 has no clean rebuild (see next table) |

## Non-functional requirements (needed for SC-Z)

| ID | Requirement | Status | Evidence or gap |
|---|---|---|---|
| NFR-1 | Total spend under $3 | Partly met | `evidence/teardown/cost_estimate.md`: about $1.20, estimated from recorded token usage. The lab role has no Cost Explorer access; a screenshot of the Cloud Lab budget panel would confirm it |
| NFR-2 | Teardown done, verify-empty saved | Met | `infra/99_teardown.sh` ran on 2026-10-11 00:11 UTC with 0 failed steps: `evidence/teardown/before.txt` (what existed), `result.txt` ("Remaining resources: none"), and `verify_empty.json` (unfiltered listings of every resource type: all empty apart from the lab's own policies and the AWS service-linked role) |
| NFR-3 | No credentials in the repo | Met | Secret scan (`AKIA`, `aws_secret`, `ASIA`) matches only the documentation example key `AKIAIOSFODNN7EXAMPLE` in test fixtures (`redteam/prompts.yaml`, `guardrail/probes.json`, `evidence/task5/guardrail_probes.jsonl`) and the words in `REQUIREMENTS.md` and `infra/CONSOLE_CHECKLIST.md`. `.gitignore` covers `.env`, `streamlit_app/.env` and `infra/state.env` |
| NFR-4 | No personal data in resource names | Met | `evidence/teardown/resource_names_review.md` (every resource name and tag reviewed; none contains personal information) |
| NFR-5 | Scripts re-runnable, versions pinned, README, console steps listed | Partly met | `README.md`; `infra/CONSOLE_CHECKLIST.md`; exact versions in `requirements.lock.txt`; `infra/03_guardrail.sh`, `04_iam_harden.sh` and `05_monitoring.sh` were each re-run during the project and converged. No clean rebuild in a fresh account was performed |
| NFR-6 | Account guard on every script | Met | `infra/lib.sh`; `tests/test_lib_guard.py` (stubbed `aws`) |
| NFR-7 | pytest passes; 80% coverage on `tools/` and dashboard aggregation | Met | 211 tests pass. Coverage on `tools/` is 92% overall. `tools/override_probe.py` is 0% and `tools/ir_probe.py` is 59% (live-probe scripts); `tools/metrics.py` is 98% |
| NFR-8 | Claims link to evidence | Partly met | Deliverables cite `evidence/` and `results/` paths throughout; this file checks only the criterion-level paths |
| NFR-9 | Gate log for create/modify/delete | Met | `STATUS.md`, section "Gate log": each gated slice, what was proposed, the approval, and what ran |

## Stand-out extras

| Extra | Evidence |
|---|---|
| CloudWatch alarms | `monitoring/alarms.json`; `evidence/task6/alarms.json`; `evidence/task6/alarm_history_prompt_attack_spike.json`; `evidence/task6/alarm_history_zero_retrieval_ratio.json`; `evidence/task6/alarm_state.jpg`; `deliverables/06_monitoring_and_ir.md` section 4 |
| 10+ prompt OWASP suite | `redteam/prompts.yaml` (24 suite cases, 3 runs each, plus IND-02 for the unlabelled poisoned-document variant: `results/matrix_poisoned_unlabelled.md`); `tools/run_suite.py`; `results/matrix_baseline_no_guardrail.md` (45 of 69), `results/matrix_hardened.md` (72 of 72); poisoned-document run `results/matrix_poisoned.md`; `deliverables/07_launch_readiness.md` |
| Expanded threat model | `deliverables/STRIDE-ML.docx` (22 threats, including T-02 multi-turn evasion, T-03 embedding supply chain, I-04 model extraction, D-01 to D-03 cost and DoS, E-05 invocation override, S-04 gateway auth); `content/stride.yaml` |
| Streamlit monitoring dashboard | `streamlit_app/pages/1_Monitoring.py`; `evidence/task7/dashboard_cloudwatch.jpg`; tests listed under SC-X4 |

## Open items

1. **NFR-1, cost:** a screenshot of the Cloud Lab budget panel would replace the estimate.
2. **NFR-5:** no clean rebuild in a fresh account.
3. **Launch conditions C1 to C9** in `deliverables/07_launch_readiness.md` section 6 are not implemented. They are recommendations for a production launch, not course requirements.
4. **Sign-off:** author and reviewer signatures in `ML-BOM.docx` and `STRIDE-ML.docx` are marked pending.

Teardown is complete: no project resource remains in the lab account.
