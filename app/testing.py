"""Deterministic stand-ins for the LLM, used by the tests and by the routing evaluation.

The routing evaluation (evals/run_routing_eval.py) pairs the REAL supervisor with these fake
specialists, so it spends tokens only on the decision it is measuring.
"""

import re

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class FakeSpecialistLLM(BaseChatModel):
    """Deterministic stand-in for the specialists' LLM.

    It really issues tool calls (so tools, ToolNode, injected runtime state and the ReAct loop are
    exercised), then summarises the tool result. Which tool it calls depends on the agent's system
    prompt. Like a real model, it only knows the arguments the tool schema exposes: no email.
    """

    @property
    def _llm_type(self) -> str:
        return "fake-specialist"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        system = " ".join(m.content for m in messages if isinstance(m, SystemMessage))
        last = messages[-1]

        if isinstance(last, ToolMessage):  # tool already ran -> final answer
            msg = AIMessage(content=f"Here is what I found: {last.content}")
            return ChatResult(generations=[ChatGeneration(message=msg)])

        text = next(m.content for m in reversed(messages) if isinstance(m, HumanMessage))
        if "Orders specialist" in system:
            order_id = re.search(r"ORD-\d+", text, re.I)
            if "cancel" in text.lower() and order_id:
                call = ("cancel_order", {"order_id": order_id.group(0)})
            elif order_id:
                call = ("get_order_status", {"order_id": order_id.group(0)})
            else:
                call = ("list_customer_orders", {})
        else:  # FAQ specialist
            call = ("search_faq", {"query": text})

        msg = AIMessage(
            content="",
            tool_calls=[{"name": call[0], "args": call[1], "id": "call_1", "type": "tool_call"}],
        )
        return ChatResult(generations=[ChatGeneration(message=msg)])


def keyword_router(messages: list) -> str:
    """Stand-in supervisor: deterministic routing by keywords + who has already replied."""
    last_human = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
    text = messages[last_human].content.lower()
    answered = {m.name for m in messages[last_human + 1 :] if isinstance(m, AIMessage) and m.name}

    if "escalation" in answered or "human_agent" in answered:
        return "FINISH"
    if re.search(r"human|angry|furious|unacceptable|complaint|lawyer", text):
        return "escalation"
    if re.search(r"ord-\d+|order|cancel", text) and "orders" not in answered:
        return "orders"
    if re.search(r"return|shipping|warranty|policy|refund|payment", text) and "faq" not in answered:
        return "faq"
    return "FINISH"
