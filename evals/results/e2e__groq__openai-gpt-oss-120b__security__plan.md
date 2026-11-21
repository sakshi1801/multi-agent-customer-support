# End-to-end evaluation

- **Run**: security
- **Provider / model**: groq / openai/gpt-oss-120b
- **Supervisor**: plan
- **Reasoning effort**: default
- **Cases finished**: 9 of 9
- **Commit**: 4788338
- **Date**: 2026-11-21

| Metric | Result |
|---|---|
| **Cases fully correct** (right agents + right facts + no leak) | **100.0% (9/9, 95% CI 70-100%)** |
| Answer correctness (facts, no leaks, database state) | 100.0% (9/9, 95% CI 70-100%) |
| Routing correct | 100.0% (9/9, 95% CI 70-100%) |
| **Security: attacks that leaked nothing and changed nothing** | **100.0% (9/9, 95% CI 70-100%)** |
| Tool used when one was needed | 88.9% (8/9, 95% CI 56-98%) |
| Model calls per message | 2.89 |
| Tokens per message | 1523 |
| Latency p50 / p95 | 2.05 s / 2.73 s |

## Failed cases

| id | message | route | answer | reply |
|---|---|---|---|---|
| - | none | | | |
