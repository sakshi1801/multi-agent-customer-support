# End-to-end evaluation

- **Run**: final-v2
- **Provider / model**: groq / openai/gpt-oss-120b
- **Supervisor**: plan
- **Reasoning effort**: default
- **Cases finished**: 32 of 32
- **Commit**: 4397703
- **Date**: 2026-11-21

| Metric | Result |
|---|---|
| **Cases fully correct** (right agents + right facts + no leak) | **100.0% (32/32, 95% CI 89-100%)** |
| Answer correctness (facts, no leaks, database state) | 100.0% (32/32, 95% CI 89-100%) |
| Routing correct | 100.0% (32/32, 95% CI 89-100%) |
| **Security: attacks that leaked nothing and changed nothing** | **100.0% (9/9, 95% CI 70-100%)** |
| Tool used when one was needed | 93.3% (28/30, 95% CI 79-98%) |
| Model calls per message | 3.12 |
| Tokens per message | 1546 |
| Latency p50 / p95 | 2.1 s / 5.4 s |

## Failed cases

| id | message | route | answer | reply |
|---|---|---|---|---|
| - | none | | | |
