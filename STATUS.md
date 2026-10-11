# STATUS

| Slice | State | Tag |
|---|---|---|
| Plan loop | PASS 91/100 (iteration 2) + rev-3 fixes | — |
| S0 Scaffold + preflight script | done | `s0-scaffold` |
| S1 Baseline agent (Task 1) | **done**: bucket, Managed KB (30/30 synced), gateway + target, harness READY, retrieval verified by API and playground | `s1-baseline` |
| S2 ML-BOM + STRIDE-ML (Tasks 2–3) | documents generate with all IDs resolved (`--check` passes); statuses to refresh after S4–S6 | — |
| S3 Guardrail (Task 5) | **done**: guardrail v2 attached, hardened prompt, lockdown guardrail v2, 27/27 probes, deliverable 05 written | `s3-guardrail` |
| S4 Least privilege (Task 4) | **done**: three roles scoped, guardrail enforced by IAM condition, 35-check simulation before/after, live bypass probes denied, rollback exercised, deliverable 04 written | `s4-iam` |
| S5 Monitoring + IR (Task 6) | **done**: invocation logging on, 11 metric filters, 4 alarms (prompt-attack alarm driven to ALARM by replay), 7 saved queries, containment script `infra/ir_contain.sh`, deliverable 06 written. Live containment drill pending (runs with S6) | `s5-monitoring` |
| S6 Validation + launch readiness (Task 7) | **done**: hardened suite 72/72 (baseline 45/69), poisoned-document test run in two variants (labelled 3/3, unlabelled 5/5 safe) and cleaned up, containment drill passed, token alarm retuned to 542, deliverable 07 written (approve with conditions) | `s6-validation` |
| S7 Monitoring dashboard | **done**: validated against the live invocation logs (128 records), screenshot `evidence/task7/dashboard_cloudwatch.jpg`; 211 tests | — |
| S8 Close-out + teardown | **done**: README, ACCEPTANCE, POSTMORTEM, SKILL-UPDATES; reports exported; independent verification SOLID (92/100); teardown run with 0 failed steps and the account verified empty (`evidence/teardown/`) | `s8-teardown` |

**Next action:** none. The project is complete and the lab account holds no project resources.

## Gate log (AWS create, modify or delete)

All on 2026-10-10. Each gated slice was described first (what would be created or changed, and the cost), and ran only after the reply shown.

| Slice | Gate | What was proposed | Approval | What ran |
|---|---|---|---|---|
| S1 | Baseline agent | Bucket, 30 documents, Managed KB, gateway and target, harness | "go S1" | `infra/01_s3.sh`; console steps for KB, gateway and harness (driven in the browser at the user's request: "you drive", "try on chrome"); `infra/02_capture_baseline.sh` |
| S2 | Inventory and threat model | No AWS change | not gated | Document generation only |
| S3 | Guardrail | Two guardrails, an inline policy for `ApplyGuardrail`, harness update (guardrail and system prompt) | "go S3" | `infra/03_guardrail.sh`, `infra/03b_probe_guardrail.sh` |
| S4 | Least privilege | New default versions of four managed policies on three roles; rollback path | "go S4" | `infra/04_iam_harden.sh` (apply, rollback once to re-capture the baseline, re-apply) |
| S5 | Monitoring | Log group, logging role, invocation logging, metric filters, alarms, saved queries | "Go s5" | `infra/05_monitoring.sh logging`, `filters` (re-applied after review fixes) |
| S6 | Validation | Containment drill on the live harness; one synthetic poisoned document, then its removal; token alarm retuned to 542 | "Go s6" | `infra/06_poison_test.sh plant`, `probe`, `clean`; `infra/07_ir_drill.sh`; `infra/05_monitoring.sh filters` |
| S8 | Teardown | Delete every resource (the list in `evidence/teardown/before.txt`) | "go teardown" | `infra/99_teardown.sh`; then unfiltered listings saved to `evidence/teardown/verify_empty.json` |

Read-only calls and model invocations (test prompts) were not gated. A second poisoned-document variant (unlabelled document) was outside the S6 approval, so it was proposed separately and run after the user replied "run variant b": `infra/06_poison_test.sh plant`, `probe`, `clean` with the `POISON_*` variables set.

