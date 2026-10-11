# Cost estimate (NFR-1: under $3)

The Cloud Lab account does not expose Cost Explorer to the lab role, and the session ended before close-out, so this
is an estimate from recorded usage, not a bill. The authoritative figure is the budget panel on the Cloud Lab page.

| Item | Basis | Estimate |
|---|---|---|
| Claude Haiku 4.5 | 560,233 input and 35,640 output tokens across all saved suite runs (`evidence/teardown/usage_totals.json`; rescored files repeat runs, so this over-counts), at an assumed list price of $1 per million input and $5 per million output tokens | about $0.74 |
| Other model calls | probes, smoke tests, the drill and guardrail checks not in the suite files; a few hundred short calls | under $0.30 |
| Titan embeddings, knowledge base sync (31 small documents, 5 syncs) | fractions of a cent per sync | under $0.05 |
| CloudWatch | 4 alarms for part of a day, under 1 MB of logs, Logs Insights queries | under $0.05 |
| S3 | 31 small objects | under $0.01 |
| **Total** | | **about $1.20, under the $3 target** |

To close NFR-1 with evidence, take a screenshot of the Cloud Lab budget panel before the lab is reset.
