# Console checklist (steps the CLI can't do)

Do these in the **Udacity Cloud Lab console**, in region **us-east-1**. Screenshot paths are relative to the repo root. Do not put personal information in any name or tag.

## 0. One-time: CLI profile (every new lab session)
1. Udacity → **Cloud Resources** → generate temporary credentials.
2. In your own terminal (not in chat), run:
   ```bash
   aws configure set aws_access_key_id <KEY> --profile udacity
   aws configure set aws_secret_access_key <SECRET> --profile udacity
   aws configure set aws_session_token <TOKEN> --profile udacity
   aws configure set region us-east-1 --profile udacity
   ```
3. Then run `export AWS_PROFILE=udacity AWS_REGION=us-east-1` and `infra/00_preflight.sh`.

## 1. Managed Knowledge Base (after `infra/01_s3.sh`)
1. **Bedrock AgentCore → Built-in tools → Knowledge Bases (KB) → Create Managed KB.** Use these settings:
   - Name: `northstar-assist-kb`
   - Additional configurations → Embeddings model: **Bedrock embeddings model** (Titan Text Embeddings V2)
   - IAM: **Create and use a new service role**
   - Data source: name `northstar-documents`, Amazon S3, This AWS account, S3 URI `s3://<BUCKET from infra/state.env>/`
2. **Create Knowledge Base**, then wait for status **Available** (2–5 minutes).
3. Select `northstar-documents` → **Sync**, and wait until the sync finishes.
4. 📸 Screenshot `evidence/task1/kb_sync.jpg`: the data-source sync result showing **0 failed** (and 30 scanned or indexed, if shown).
5. 📸 Screenshot `evidence/task1/kb_details.jpg`: the KB details page with status Available, the service role name, `amazon.titan-embed-text-v2:0`, and 1024 dimensions.
6. Record the IDs:
   - `infra/set_state.sh KB_ID <knowledge base id>`
   - `infra/set_state.sh KB_ROLE_NAME <service role name>`

## 2. Gateway
1. **AgentCore → Gateways → Create Gateway**, with these settings:
   - Name: `northstar-assist-gateway`
   - Inbound auth: **Use IAM permissions**
   - Permissions: **Create default role**
2. Configure the target:
   - Target name: `northstar-kb`
   - Protocol: **MCP target**
   - Type: **Connectors → Knowledge Bases (KB)**
   - Retrieval: **Standard retrieval**
   - KB: `northstar-assist-kb`
   - Outbound auth: **IAM Role**
   - Tool description: `Search Northstar Technologies internal documents (policies, procedures, reports, spreadsheets) and return relevant passages with source documents.`
3. **Create Gateway**, then wait until both the gateway and the target show **Ready**.
4. Run `infra/set_state.sh GATEWAY_ID <gateway id>`.

## 3. Harness
1. **AgentCore → Harness → (dropdown) Advanced create Harness**, with:
   - Name: `NorthstarAssist`
   - Model: Bedrock / Bedrock, then the pencil icon → **Anthropic → Claude Haiku 4.5** → Apply
   - System prompt: the course prompt, verbatim (copied below). Leave Parameters empty.
   - Memory: **off**
   - Tools: **Gateway on**, set to `northstar-assist-gateway`, Outbound auth **IAM role**. All other tools off.
   - Permissions: **Create default role**
2. **Create Harness**, then wait for **Ready**.
3. Run `infra/set_state.sh HARNESS_ARN <harness ARN>`, then `infra/02_capture_baseline.sh`.

Baseline system prompt:
```
You are Northstar Assist, Northstar Technologies' internal employee assistant. Your job is to help Northstar employees find accurate answers to questions about company policies, procedures, and internal documentation. Always search the Northstar knowledge base tool before answering a question about Northstar. Base your answers only on the retrieved documents and name the source document you used. Do not make up policy details. If the knowledge base does not contain relevant information, say so clearly. Do not guess. Do not discuss topics unrelated to Northstar operations.
```

## 4. Playground evidence (Task 1)
1. **Test → Harness playground**, select `NorthstarAssist` → **Test Harness**.
2. Prompt: `What is Northstar's hybrid work policy? Name the source document.` → Run.
3. 📸 `evidence/task1/playground_answer.jpg`: the answer.
4. 📸 `evidence/task1/playground_retrieve_trace.jpg`: click the **Northstar-Kb Retrieve** tool call. Show the retrievalQuery, the chunks, the document title, the S3 location and the score.

## 5. Later screenshots (one per slice; the scripts tell you when)
- `evidence/task5/guardrail_blocked_injection.jpg` and `guardrail_blocked_topic.jpg` (playground, new session, after S3)
- `evidence/task6/invocation_logging_on.jpg` (Bedrock → Settings → Model invocation logging)
- `evidence/task6/alarm_state.jpg` (CloudWatch → Alarms)
- `evidence/task7/dashboard.jpg` (Streamlit monitoring page)
