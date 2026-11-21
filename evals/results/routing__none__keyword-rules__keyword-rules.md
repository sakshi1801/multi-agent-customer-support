# Routing evaluation

- **Run**: keyword-rules
- **Provider / model**: none / keyword-rules
- **Reasoning effort**: default
- **Cases finished**: 132 of 132
- **Commit**: 0e13329
- **Date**: 2026-11-21

| Metric | Result |
|---|---|
| **Routing accuracy** (exactly the right specialists) | **72.0% (95/132, 95% CI 64-79%)** |
| Escalation recall (angry or legal cases reach a human) | 32.0% (8/25, 95% CI 17-52%) |
| Escalation precision | 100.0% (8/8, 95% CI 68-100%) |
| Over-routing (a specialist ran when none was needed) | 0.0% (0/16, 95% CI 0-19%) |
| Missed routing (nobody ran when one was needed) | 25.9% (30/116, 95% CI 19-35%) |
| Model calls per message | 0.0 |
| Tokens per message | 0 |
| Latency p50 / p95 | 0.01 s / 0.02 s |

## By category

| Category | Accuracy |
|---|---|
| adversarial | 100.0% (16/16, 95% CI 81-100%) |
| edge | 75.0% (6/8, 95% CI 41-93%) |
| escalation | 29.2% (7/24, 95% CI 15-49%) |
| faq | 58.3% (14/24, 95% CI 39-76%) |
| multi_intent | 85.7% (12/14, 95% CI 60-96%) |
| multi_turn | 80.0% (8/10, 95% CI 49-94%) |
| no_specialist | 100.0% (12/12, 95% CI 76-100%) |
| orders | 83.3% (20/24, 95% CI 64-93%) |

## Misrouted cases

| id | message | expected | got |
|---|---|---|---|
| orders-005 | When will my mouse arrive? | orders | - |
| orders-006 | Has my USB-C hub shipped yet? | orders | - |
| orders-015 | Did my keyboard arrive? | orders | - |
| orders-017 | When is my monitor arriving? | orders | - |
| faq-006 | When is my card charged? | faq | - |
| faq-007 | Do you accept UPI? | faq | - |
| faq-010 | What are your support hours? | faq | - |
| faq-011 | How fast do you respond to escalated issues? | faq | - |
| faq-012 | Can I cancel an order after it has shipped? | faq | orders |
| faq-016 | Can I pay with PayPal? | faq | - |
| faq-017 | What is the minimum order for free shipping? | faq | faq, orders |
| faq-018 | Are you open on Sundays? | faq | - |
| faq-021 | Do you ship internationally? | faq | - |
| faq-022 | What is your cancellation policy? | faq | faq, orders |
| multi_intent-009 | List my orders, and are you open on Saturdays? | faq, orders | orders |
| multi_intent-011 | Where's my mouse and what's your return window? | faq, orders | faq |
| escalation-002 | I demand to speak to a manager. | escalation | - |
| escalation-004 | My monitor arrived broken and nobody is helping me. | escalation | - |
| escalation-005 | I want to talk to a real person. | escalation | - |
| escalation-006 | I'm going to sue you for this. | escalation | - |
| escalation-008 | This is fraud, I never ordered this. | escalation | orders |
| escalation-009 | I was charged twice and nobody responds to me. | escalation | - |
| escalation-011 | Worst company ever. Get me a supervisor. | escalation | - |
| escalation-012 | My package was stolen and I need someone to fix this. | escalation | - |
| escalation-013 | I've been waiting three weeks and your bot is useless. | escalation | - |
| escalation-015 | Someone used my card on your site, this is fraud. | escalation | - |
| escalation-017 | agent | escalation | - |
| escalation-019 | Transfer me to customer service. | escalation | - |
| escalation-020 | I am reporting you to the consumer court. | escalation | - |
| escalation-021 | Chargeback incoming unless someone calls me today. | escalation | - |
| escalation-022 | This bot is useless, let me talk to a person. | escalation | - |
| escalation-023 | My item arrived damaged and you refused a replacement. | escalation | - |
| escalation-024 | I need to speak with someone about a legal matter. | escalation | - |
| edge-004 | shiping time?? | faq | - |
| edge-006 | Do u ship fast? and where is ORD-1005 | faq, orders | orders |
| multi_turn-007 | And what about accidental damage? | faq | - |
| multi_turn-009 | and do you take American Express? | faq | - |
