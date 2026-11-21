"""Optional prompt-injection guard: Llama Prompt Guard 2 (free on Groq) scores every customer message.

This is an EXTRA layer. The real protection against one customer reaching another's data is the
ownership check inside the tools (app/orders.py), which no wording can talk its way around. The guard
adds cheap early rejection of the blunt attacks ("Ignore all previous instructions ...") and a log
signal for them. evals/results/guard.md measures what it catches and what it wrongly blocks.
"""

import logging
import os

logger = logging.getLogger(__name__)

PROMPT_GUARD_MODEL = "meta-llama/llama-prompt-guard-2-86m"
REFUSAL = (
    "Sorry, I can't help with that request. I can look up your own orders, explain our store policies, "
    "or connect you with a human agent."
)


class PromptGuard:
    """Returns the probability (0-1) that a message is a prompt-injection attempt."""

    def __init__(
        self, api_key: str | None = None, base_url: str | None = None, model: str = PROMPT_GUARD_MODEL
    ):
        from openai import OpenAI

        from app.config import GROQ_BASE_URL

        self.model = model
        self.client = OpenAI(
            api_key=api_key or os.environ["GROQ_API_KEY"], base_url=base_url or GROQ_BASE_URL, max_retries=2
        )

    def score(self, text: str) -> float:
        reply = self.client.chat.completions.create(
            model=self.model, messages=[{"role": "user", "content": text}], timeout=15
        )
        return float(reply.choices[0].message.content)


def make_guard(threshold: float = 0.5, scorer=None):
    """A function text -> True when the message should be refused.

    Fails open: if the scoring service is down or rate limited the message goes on to the normal
    pipeline, whose ownership checks do not depend on the guard.
    """
    scorer = scorer or PromptGuard().score

    def is_attack(text: str) -> bool:
        try:
            score = scorer(text)
        except Exception:
            logger.exception("prompt guard unavailable; letting the message through")
            return False
        if score >= threshold:
            logger.warning("prompt injection suspected (score %.3f): %.80r", score, text)
        return score >= threshold

    return is_attack
