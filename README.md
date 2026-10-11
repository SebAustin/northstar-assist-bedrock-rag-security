# Northstar Assist: build, harden and validate a RAG agent on Amazon Bedrock AgentCore

Northstar Assist is an internal question-answering agent for the fictional company Northstar Technologies. It answers employee questions from 30 synthetic company documents and names the source document it used. It runs on Amazon Bedrock AgentCore (a Harness running Claude Haiku 4.5, a Gateway, and a Managed Knowledge Base over S3). This repository is the finished Udacity "AI Security Engineer" project: the agent was deployed, hardened (guardrail, least-privilege IAM, monitoring) and validated in a temporary AWS Cloud Lab account, and the seven course deliverables are in `deliverables/`.

## Architecture

```
Employee / Streamlit app
        |  InvokeHarness (IAM caller)
        v
AgentCore Harness  -- Claude Haiku 4.5 (US inference profile), system prompt v2, memory off
   |   ^  Bedrock Guardrail on model input and output (attached through guardrailConfig)
   |   +- model-invocation logs --> CloudWatch Logs --> metric filters --> alarms
   v
AgentCore Gateway (MCP, IAM inbound auth)  -- one read-only tool: Retrieve
   v
Managed Knowledge Base (Titan Text Embeddings V2, 1024 dimensions)
   v
S3 bucket: 30 documents (private, SSE-S3, versioned)
```

All resources are in `us-east-1`. The documents contain synthetic personal and customer data only.

## Headline results

| Area | Result | Source |
|---|---|---|
| Baseline agent | Knowledge base sync: 30 scanned, 30 indexed, 0 failed. Smoke prompt returns a grounded answer citing `company_policies_handbook.html` | `deliverables/01_harness_evidence.md` |
| Validation suite | 24 cases, 3 runs each (plus one case for the unlabelled poisoned-document variant). Baseline passed 45 of 69 runs; hardened system passed 72 of 72, with 0 of 12 benign runs blocked | `deliverables/07_launch_readiness.md` sections 1 and 3 |
| Worst baseline failure | A multi-turn request returned 25 employee email addresses in 1 run of 3; blocked 3 of 3 after hardening | `deliverables/07_launch_readiness.md` section 3 |
| IAM | Harness execution policy cut from 21 to 13 statements. Simulated checks allowed: 22 before, 10 after; denied: 13 before, 25 after. A per-request override that dropped the guardrail worked before and now returns `AccessDenied` | `deliverables/04_iam_hardening.md` section 1 |
| Guardrail | 27 of 27 control probes behaved as designed | `deliverables/05_safety_controls.md` section 6 |
| Monitoring | 11 metric filters, 4 alarms, 7 saved queries; the prompt-attack alarm was driven to ALARM by replayed attacks; containment drill passed for both levels | `deliverables/06_monitoring_and_ir.md` section 1 |
| Launch verdict | **Approve with conditions**: 9 conditions, 4 of them to close before employees use the assistant | `deliverables/07_launch_readiness.md` sections 1 and 6 |

## Deliverables index

Markdown sources are in `deliverables/`. Every deliverable is also exported to `.docx` and `.pdf` in `deliverables/export/`. `ML-BOM` and `STRIDE-ML` are filled copies of the course templates.

| Course task | Source | Exported |
|---|---|---|
| 1. Working harness with retrieval | `deliverables/01_harness_evidence.md` | `deliverables/export/01_harness_evidence.docx`, `.pdf` |
| 2. ML-BOM | `deliverables/ML-BOM.docx` (from `content/mlbom.yaml`) | `deliverables/export/ML-BOM.docx`, `.pdf` |
| 3. STRIDE-ML threat model | `deliverables/STRIDE-ML.docx` (from `content/stride.yaml`) | `deliverables/export/STRIDE-ML.docx`, `.pdf` |
| 4. Least-privilege IAM | `deliverables/04_iam_hardening.md` | `deliverables/export/04_iam_hardening.docx`, `.pdf` |
| 5. Safety controls | `deliverables/05_safety_controls.md` | `deliverables/export/05_safety_controls.docx`, `.pdf` |
| 6. Monitoring plan and IR playbook | `deliverables/06_monitoring_and_ir.md` | `deliverables/export/06_monitoring_and_ir.docx`, `.pdf` |
| 7. Validation and launch readiness | `deliverables/07_launch_readiness.md` | `deliverables/export/07_launch_readiness.docx`, `.pdf` |

`ACCEPTANCE.md` maps every rubric line to its evidence and lists open items.

## Repository layout

| Path | Content |
|---|---|
| `deliverables/` | The seven deliverables and their exports |
| `evidence/task1` to `task7` | Raw CLI output, probe results and screenshots behind each claim |
| `infra/` | Numbered shell scripts, `ir_contain.sh`, shared guard in `lib.sh`, `CONSOLE_CHECKLIST.md`, `state.env` (resource IDs, git-ignored) |
| `tools/` | Python: harness client and stream parser, red-team suite runner, metrics, probes, template filler, `export_docs.sh` |
| `guardrail/`, `iam/`, `monitoring/` | Guardrail config and system prompt v2; IAM policies before and after; metric filters, alarms and saved queries |
| `redteam/prompts.yaml` | The 24-case OWASP LLM01 to LLM10 suite with pass rules |
| `results/` | Suite runs (`.jsonl`) and result matrices (`.md`) |
| `streamlit_app/` | Starter chat app (`app.py`) plus the monitoring page `pages/1_Monitoring.py` |
| `tests/` | pytest suite (account guard, parsers, metrics, template filler, dashboard) |
| `content/` | YAML source for ML-BOM and STRIDE-ML |
| `starter/` | Course starter files, kept unmodified |
| `REQUIREMENTS.md`, `PLAN.md`, `ASSUMPTIONS.md`, `STATUS.md` | Requirements, plan, assumptions log, slice status |

## Prerequisites

AWS CLI v2, `jq`, Python 3 with a virtual environment, and for the document export `pandoc` and LibreOffice (`soffice`). Create the environment with `python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`.

## Reproduce the build

**Safety guard.** Every script in `infra/` calls `require_lab_account` in `infra/lib.sh` first. It exits unless `AWS_PROFILE=udacity`, `AWS_REGION=us-east-1`, and, if you set `NORTHSTAR_PERSONAL_ACCOUNT_ID` to an account ID you never want touched, the profile does not resolve to that account. Create the `udacity` profile from the lab's temporary credentials in your own terminal (steps in `infra/CONSOLE_CHECKLIST.md`), then run `export AWS_PROFILE=udacity AWS_REGION=us-east-1`. Scripts that create or change resources ask for confirmation first.

**Console steps.** The Managed Knowledge Base and the Gateway were created in the AWS console, and the Harness form was started there; the harness itself was then created with `create-harness` after the console form hung (`ASSUMPTIONS.md` A11). Follow `infra/CONSOLE_CHECKLIST.md` and record each ID with `infra/set_state.sh KEY VALUE`.

| Step | Command | What it does |
|---|---|---|
| 1 | `infra/00_preflight.sh` | Probes what the lab credentials may do; writes `evidence/preflight.json` |
| 2 | `infra/01_s3.sh` | Creates the private, encrypted, versioned bucket and uploads the 30 documents |
| 3 | Console, per `infra/CONSOLE_CHECKLIST.md` | Create and sync the Managed KB, the Gateway and its target, and the Harness |
| 4 | `infra/02_capture_baseline.sh` | Verifies the three resources and snapshots their default IAM roles |
| 5 | `.venv/bin/python tools/run_suite.py --smoke` | Sends the smoke prompt and saves the transcript |
| 6 | `infra/03_guardrail.sh`, then `infra/03b_probe_guardrail.sh` | Creates and versions the guardrails, attaches one with prompt v2, runs the control probes |
| 7 | `infra/04_iam_harden.sh` | Replaces the three default policies with `iam/after/`, then simulates (`--simulate`, `--rollback` also available) |
| 8 | `infra/05_monitoring.sh logging`, then `filters`, then `status` | Turns on invocation logging; creates metric filters, alarms, saved queries |
| 9 | `.venv/bin/python tools/run_suite.py --runs 3 --label hardened` | Runs the 24-case suite three times each |
| 10 | `infra/06_poison_test.sh` | Plants a labelled synthetic poisoned document, probes it, removes it |
| 11 | `infra/07_ir_drill.sh` (uses `infra/ir_contain.sh`) | Exercises both containment levels on the live harness and recovers |
| 12 | `.venv/bin/python tools/fill_templates.py --check`, then without `--check` | Regenerates ML-BOM and STRIDE-ML from `content/` |
| 13 | `tools/export_docs.sh` | Exports the deliverables to `deliverables/export/` |
| 14 | `infra/99_teardown.sh` | Removes every resource (see below) |

## Run the tests and the dashboard

```bash
.venv/bin/pytest -q                         # 211 tests, no AWS access needed (AWS CLI is stubbed)
.venv/bin/streamlit run streamlit_app/app.py
```

Open the **Monitoring** page from the sidebar. It shows guardrail intervention rate, token usage, retrieval success and recent blocked sessions. The default source reads `results/*.jsonl` offline. The "CloudWatch Logs Insights" source needs live invocation logs and valid lab credentials, so it works only while the lab resources exist. The chat page needs `AGENTCORE_HARNESS_ARN` in a git-ignored `.env`.

## Known limits

From `deliverables/07_launch_readiness.md` sections 7 and 8:

- Indirect injection rests on one layer: no guardrail screens retrieved text, and contextual grounding does not run through the harness.
- Three runs per case detect behaviour that fails often; a failure that happens one time in ten appears in about one three-run test in four.
- Results apply to one model version, one prompt and one guardrail version, tested on one day.
- The data is synthetic, and the poisoned document labelled itself, which a real attacker would not do.
- No load, cost or concurrency testing, and no real user identities.
- The suite was written by the team that built the controls; an independent red team would find other cases.
- The alarms have no notification target (the lab forbids contact details), and invocation logs are kept for seven days.

## Temporary resources and teardown

All AWS resources live in a temporary Udacity Cloud Lab account and do not outlive it. `infra/99_teardown.sh` removes them in dependency order and saves a verify-empty listing under `evidence/`. It ran only after the evidence was confirmed complete. Now that teardown is done, scripts that call AWS and the CloudWatch source of the dashboard will no longer work; the tests, the offline dashboard and all documents still do.

Teardown ran on 2026-10-11 (00:11 UTC) with no failed steps. The account was then checked with unfiltered listings and holds no project resources: `evidence/teardown/result.txt`, `evidence/teardown/verify_empty.json`.

## Licence and course material

`starter/` (the two document templates, the 30 sample knowledge-base documents and the original Streamlit app) is Udacity educational content, copied unchanged from the course's public starter repository and covered by Udacity's licence in `starter/LICENSE.md` (non-commercial use). `streamlit_app/app.py` is that starter app; the monitoring page and everything outside `starter/` were written for this project. All company data in the knowledge base is fictional.
