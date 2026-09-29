# Benchmark: rules vs LLM

Each message runs through the real agent loop. Sensitive messages never reach the LLM (the guardrail
runs first), the distribution always comes from the lookup tool, and the priority from the written
policy. **samples** are the 23 messages the rules were written with; **holdout** are 14 new messages
the rules were not tuned on.

## samples (23 messages)

| Metric | rules | LLM |
|---|---|---|
| Category correct | 23/23 (100%) | — |
| Priority correct | 23/23 (100%) | — |
| Action correct (refer / ask / draft) | 23/23 (100%) | — |
| Distribution linked correctly | 7/7 (100%) | — |
| Drafts passing the safety check | 13/13 (100%) | — |
| Drafts written by the LLM (kept) | 0/13 (0%) | — |
| Fell back to rules | 0/23 (0%) | — |

**Misses (rules):** none

## holdout (14 messages)

| Metric | rules | LLM |
|---|---|---|
| Category correct | 8/14 (57%) | — |
| Priority correct | 7/14 (50%) | — |
| Action correct (refer / ask / draft) | 11/14 (79%) | — |
| Distribution linked correctly | 4/4 (100%) | — |
| Drafts passing the safety check | 13/13 (100%) | — |
| Drafts written by the LLM (kept) | 0/13 (0%) | — |
| Fell back to rules | 0/14 (0%) | — |

**Misses (rules):** 
- H05: got information/Low/draft_response, expected access/High/draft_response
- H06: got access/Medium/draft_response, expected access/High/draft_response
- H08: got conduct/Medium/draft_response, expected appreciation/Low/draft_response
- H10: got information/Low/draft_response, expected sensitive/Critical/escalate
- H11: got conduct/Medium/draft_response, expected sensitive/Critical/escalate
- H12: got information/Low/draft_response, expected sensitive/Critical/escalate
- H14: got information/Low/draft_response, expected distribution/Medium/draft_response

