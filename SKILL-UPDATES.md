# Proposed workflow updates (for human review; nothing here has been applied)

Source: `POSTMORTEM.md` for the Northstar Assist capstone. Each item is additive and traceable to an incident. None relaxes a guardrail or quality bar. Target files belong in the shared plugin repo (`skills/<name>/SKILL.md`, `agents/<name>.md`), not in generated ports; this project does not edit them.

## 1. Pipe-safe evidence capture

- **Lesson:** A rollback failed silently because the script's output went through `tail` inside an `&&` chain. The pipeline returned `tail`'s status, and hardened-state results were saved as "before" evidence (incident 1).
- **Proposed wording:** "Any command whose success matters is run without a pipe, or with `set -o pipefail` and the exit code checked. Do not chain state-changing steps with `&&` into a filter (`tail`, `head`, `tee`, `grep`). After a state-changing step, read the state back and assert it, then capture evidence. Run multi-step cloud changes one step at a time when the state is evidence."
- **Where:** Builder checklist (shell and infra scripts); also the reviewer prompt as a grep-able smell: `| tail`, `| head` or `| grep` directly after an `aws` or state-changing call.

## 2. Self-describing before/after evidence

- **Lesson:** Nothing in the "before" file showed it was a "before". Only a human reading the numbers caught it (incident 1, "what was lucky").
- **Proposed wording:** "Evidence files that compare two states carry an identifier of the state they describe (version id, hash, timestamp) in the file itself. The script that produces the comparison fails if the two identifiers are equal or if the before-identifier is not the original."
- **Where:** Builder checklist; solution-verifier prompt (spot-check one before/after pair per project).

## 3. Preflight probes the recovery path

- **Lesson:** The lab denied `iam:SetDefaultPolicyVersion`, which only mattered at rollback time. Preflight tested the forward calls (incidents 1 and 8).
- **Proposed wording:** "For each resource type the plan changes, the preflight lists the forward call, the rollback call and the delete call, and probes all three (simulation or a harmless create-and-delete). The plan lists the fallback for each denied call before any slice starts. Rollback is exercised once before the slice is marked done."
- **Where:** Plan rubric (environment and permissions criterion); deployment-readiness checklist.

## 4. Test isolation from evidence and from real infra

- **Lesson:** A test ran a real script against a stub CLI and overwrote four uncommitted evidence files, because the script ignored the test's output directory (incident 4).
- **Proposed wording:** "Every script that writes evidence reads its output root from one variable, and every test that runs such a script sets it to a temporary directory. A test may not touch tracked or untracked evidence paths. Before running new tests that execute infra scripts, commit or copy the current evidence."
- **Where:** Test-engineer prompt; builder checklist.

## 5. Observed-value capture before parser code

- **Lesson:** The stop reason came from documentation and was wrong; "a block has zero output tokens" came from a single sample and was wrong (incidents 2 and 3). The assumptions log kept the wrong value (A5) after the fix.
- **Proposed wording:** "Any value a parser, filter or alarm depends on (field names, enum values, counts) is first captured from a real record produced by the live system, for every class it must separate (success, block, masked, error). The record is stored as a fixture. Where an assumption is later disproved, the assumptions log entry is amended in the same commit."
- **Where:** Test-engineer prompt; plan rubric (assumptions criterion: each assumption has a probe or is marked unverified).

## 6. Control tests include benign near-neighbours and a bypass check

- **Lesson:** A denied topic blocked legitimate password-policy questions; a lockdown rule let a poem through (incident 2).
- **Proposed wording:** "For each content rule, the test set has at least two legitimate inputs that share the rule's vocabulary (must pass) and at least two hostile inputs written in other words (must block). For any 'block all' or 'deny all' control, one harmless unrelated input must also be blocked. Report the false-positive count with the result."
- **Where:** Security-auditor prompt; test-engineer prompt; solution rubric (safety-controls criterion).

## 7. Attack fixtures must be neutral, and results attributed to a layer

- **Lesson:** The synthetic poisoned file labelled itself a test and carried the word "poisoned" in its name. The output guardrail blocked on that word, and the result credited the wrong control (incident 5).
- **Proposed wording:** "Attack fixtures use neutral names and content that does not describe itself as a test; a label such as 'synthetic' lives in metadata outside the text the system reads. Every security test result states which control acted, taken from a trace or log, not from the final status. If the acting control is not the one under test, the run is recorded as unattributed and the fixture is revised before the result is used."
- **Where:** Security-auditor prompt; test-engineer prompt; threat-model skill (indirect injection section).

## 8. Reviewer checklist for incident playbooks and shell loops

- **Lesson:** The reviewer found a playbook step that would undo containment, and a `while read ... done < <(jq ...)` loop that skipped every alarm silently (incident 3). Both were found by review, not by tests.
- **Proposed wording:** "Operational playbooks are read as a state sequence: for each step, state what is changed and what earlier step it could undo. Shell loops fed by process substitution or command substitution are checked for the empty-input case; scripts that create N things assert N were created and exit non-zero otherwise."
- **Where:** Independent reviewer prompt; solution rubric (operational-scripts criterion). Keep the independent review step for any slice with scripts or playbooks.

## 9. Credential handling in the intake step

- **Lesson:** Cloud keys were pasted into the chat (incident 6). The refusal worked, but the keys still counted as exposed.
- **Proposed wording:** "At project start, the requirements step states how cloud access is provided: a named CLI profile configured outside the chat. If keys appear in a message, the agent does not use them, tells the user to rotate them, and records the event in the assumptions log without the key value."
- **Where:** Requirements/intake prompt; add one line to the secrets guardrail text (wording only, no relaxation).

## 10. Schedule teardown against session lifetime

- **Lesson:** The temporary session expired after the last evidence capture and before teardown, so teardown moved to a new session (incident 7).
- **Proposed wording:** "When the environment has a limited session or budget, the plan states the session length, orders the work so that teardown can run in the same session as the last evidence capture, and lists a read-only inventory command to run before every expected expiry. Teardown still requires explicit user approval."
- **Where:** Plan rubric (cost and session risk criterion); deployment-readiness checklist.
