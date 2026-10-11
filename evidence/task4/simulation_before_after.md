| Role | Action | Resource | What the check represents | Before | After |
|---|---|---|---|---|---|
| HARNESS | `bedrock:InvokeModelWithResponseStream` | `bedrock:us-east-1:<acct>:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0` | The approved inference profile, with the Northstar guardrail attached | allowed | allowed |
| HARNESS | `bedrock:InvokeModelWithResponseStream` | `bedrock:us-east-1:<acct>:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0` | The approved profile called WITHOUT the Northstar guardrail (per-request override) | allowed | **denied** |
| HARNESS | `bedrock:InvokeModelWithResponseStream` | `bedrock:us-east-1:<acct>:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0` | The approved profile called with some other guardrail | allowed | **denied** |
| HARNESS | `bedrock:InvokeModelWithResponseStream` | `bedrock:us-east-2::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0` | Haiku 4.5 in a destination Region, called through the profile, with the Northstar guardrail attached | allowed | allowed |
| HARNESS | `bedrock:InvokeModelWithResponseStream` | `bedrock:us-east-1::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0` | Haiku 4.5 called directly, not through the profile | allowed | **denied** |
| HARNESS | `bedrock:InvokeModelWithResponseStream` | `bedrock:us-east-1:<acct>:inference-profile/us.amazon.nova-2-lite-v1:0` | A different model's inference profile | allowed | **denied** |
| HARNESS | `bedrock:InvokeModel` | `bedrock:us-east-1::foundation-model/amazon.nova-2-lite-v1:0` | A different foundation model | allowed | **denied** |
| HARNESS | `bedrock:InvokeModel` | `bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0` | A larger, costlier model | allowed | **denied** |
| HARNESS | `bedrock:ApplyGuardrail` | `bedrock:us-east-1:<acct>:guardrail/753a9dgwqe2f` | The Northstar guardrail | allowed | allowed |
| HARNESS | `bedrock:ApplyGuardrail` | `bedrock:us-east-1:<acct>:guardrail/1oom74pzn70o` | The IR lockdown guardrail | allowed | allowed |
| HARNESS | `bedrock:ApplyGuardrail` | `bedrock:us-east-1:<acct>:guardrail/aaaaaaaaaaaa` | Any other guardrail | denied | denied |
| HARNESS | `bedrock-agentcore:InvokeGateway` | `bedrock-agentcore:us-east-1:<acct>:gateway/northstar-assist-gateway-hd1uvsa8f3` | The Northstar gateway | allowed | allowed |
| HARNESS | `bedrock-agentcore:InvokeGateway` | `bedrock-agentcore:us-east-1:<acct>:gateway/other-gateway-abc123` | Any other gateway | denied | denied |
| HARNESS | `bedrock:Retrieve` | `bedrock:us-east-1:<acct>:knowledge-base/WUWHZC06MP` | Direct KB retrieval, bypassing the gateway | denied | denied |
| HARNESS | `bedrock-agentcore:StartBrowserSession` | `bedrock-agentcore:us-east-1:aws:browser/aws.browser.v1` | Browser tool (not configured) | allowed | **denied** |
| HARNESS | `bedrock-agentcore:InvokeCodeInterpreter` | `bedrock-agentcore:us-east-1:aws:code-interpreter/aws.codeinterpreter.v1` | Code Interpreter (not configured) | allowed | **denied** |
| HARNESS | `bedrock-agentcore:RetrieveMemoryRecords` | `bedrock-agentcore:us-east-1:<acct>:memory/NorthstarAssist-abc` | Memory (disabled) | allowed | **denied** |
| HARNESS | `elasticfilesystem:ClientWrite` | `elasticfilesystem:us-east-1:<acct>:file-system/fs-12345678` | EFS mounts (not configured) | denied | denied |
| HARNESS | `bedrock-mantle:CreateInference` | `bedrock-mantle:us-east-1:<acct>:project/default` | Bedrock Mantle API (not used) | allowed | **denied** |
| HARNESS | `s3:GetObject` | `s3:::northstar-assist-kb-5ca661ad/csv/employee_directory.csv` | Direct read of the source documents | denied | denied |
| HARNESS | `logs:CreateLogGroup` | `logs:us-east-1:<acct>:log-group:/aws/bedrock-agentcore/runtimes/harness_NorthstarAssist-92Prr07JAK-DEFAULT` | Its own runtime log group | allowed | allowed |
| HARNESS | `logs:CreateLogGroup` | `logs:us-east-1:<acct>:log-group:/aws/bedrock-agentcore/runtimes/other-runtime-DEFAULT` | Another runtime's log group | allowed | **denied** |
| GATEWAY | `bedrock:Retrieve` | `bedrock:us-east-1:<acct>:knowledge-base/WUWHZC06MP` | The Northstar knowledge base | allowed | allowed |
| GATEWAY | `bedrock:GetKnowledgeBase` | `bedrock:us-east-1:<acct>:knowledge-base/WUWHZC06MP` | The Northstar knowledge base | allowed | allowed |
| GATEWAY | `bedrock:Retrieve` | `bedrock:us-east-1:<acct>:knowledge-base/OTHERKB123` | Any other knowledge base | denied | denied |
| GATEWAY | `bedrock:AgenticRetrieveStream` | `*` | Agentic retrieval (not configured; the action has no resource-level permissions) | allowed | **denied** |
| GATEWAY | `bedrock:InvokeModel` | `bedrock:us-east-1::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0` | Model invocation by the gateway | denied | denied |
| GATEWAY | `bedrock:Rerank` | `*` | Reranking (not configured) | denied | denied |
| GATEWAY | `bedrock:ApplyGuardrail` | `bedrock:us-east-1:<acct>:guardrail/753a9dgwqe2f` | Guardrails are applied by the harness, not the gateway | denied | denied |
| GATEWAY | `s3:GetObject` | `s3:::northstar-assist-kb-5ca661ad/csv/employee_directory.csv` | Direct read of the source documents | denied | denied |
| KB | `bedrock:InvokeModel` | `bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0` | The embedding model | allowed | allowed |
| KB | `bedrock:InvokeModel` | `bedrock:us-east-1::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0` | A generation model | denied | denied |
| KB | `s3:GetObject` | `s3:::northstar-assist-kb-5ca661ad/html/company_policies_handbook.html` | Reading the document bucket | allowed | allowed |
| KB | `s3:PutObject` | `s3:::northstar-assist-kb-5ca661ad/html/company_policies_handbook.html` | Writing to the document bucket | denied | denied |
| KB | `aws-marketplace:Subscribe` | `*` | Marketplace subscriptions (not needed for Titan) | denied | denied |
