"""Supervisor multi-agent graph for customer support.

      START
        |
    supervisor  <-----------------+
     /   |    \\                   |
orders  faq  escalate             |  (each specialist returns to the
   |     |      |                 |   supervisor, max MAX_HOPS hops)
   +-----+      v                 |
   |        human_review  --------+     <- pauses with interrupt() until a
   |        (human-in-the-loop)            human agent replies
   +----------------------------+
                                 FINISH -> END
"""

from collections.abc import Callable
from typing import Literal

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from app import tools

MAX_HOPS = 3

ROUTES = ("orders", "faq", "escalation", "FINISH")


class Route(BaseModel):
    """Supervisor decision: which specialist should act next."""

    next: Literal["orders", "faq", "escalation", "FINISH"] = Field(
        description="The next specialist to run, or FINISH if the customer's request is fully handled."
    )


class SupportState(MessagesState):
    next: str
    hops: int
    customer_email: str
    ticket_id: int | None


SUPERVISOR_PROMPT = """You are the supervisor of a customer-support team. Read the conversation and pick ONE next step:

- orders: questions about a specific order, order status, tracking, listing a customer's orders, or cancelling an order.
- faq: general policy questions (shipping, returns, refunds, payments, warranty, contact hours).
- escalation: the customer is angry or upset, asks for a human, reports something the other agents can't solve (damaged item dispute, fraud, legal threats), or an agent could not help.
- FINISH: every part of the customer's latest message has already been answered by a specialist.

Rules:
- Look at which specialists have already replied to the latest customer message. Do not send the same question to the same specialist twice.
- A message with two parts (e.g. order status AND return policy) should visit both specialists, one at a time, then FINISH.
- Never answer the customer yourself."""

ORDERS_PROMPT = """You are the Orders specialist for an online electronics store.
Use your tools to look up facts. Never invent order data.
If the customer gives no order ID, use their email (provided in the system context) with list_customer_orders.
Only cancel an order if the customer clearly asks to cancel it.
Reply in 1-3 friendly, concise sentences."""

FAQ_PROMPT = """You are the Policy FAQ specialist for an online electronics store.
Always call search_faq first and answer ONLY from what it returns.
If the FAQ does not cover the question, say you're not sure and suggest contacting support.
Reply in 1-3 friendly, concise sentences."""


def make_llm_router(llm) -> Callable[[list], str]:
    """Router that asks the LLM for a structured Route decision."""
    structured = llm.with_structured_output(Route)

    def route(messages: list) -> str:
        decision = structured.invoke([SystemMessage(SUPERVISOR_PROMPT), *messages])
        return decision.next

    return route


def _last_text(result: dict) -> str:
    content = result["messages"][-1].content
    return content if isinstance(content, str) else str(content)


def build_graph(llm=None, router: Callable[[list], str] | None = None, checkpointer=None):
    """Build and compile the support graph.

    llm          chat model used by the specialists (and the default router)
    router       optional override: fn(messages) -> 'orders'|'faq'|'escalation'|'FINISH'
    checkpointer needed for human-in-the-loop; defaults to in-memory
    """
    if llm is None:
        from app.config import get_llm

        llm = get_llm()
    router = router or make_llm_router(llm)

    orders_agent = create_agent(llm, tools.ORDER_TOOLS, system_prompt=ORDERS_PROMPT)
    faq_agent = create_agent(llm, tools.FAQ_TOOLS, system_prompt=FAQ_PROMPT)

    # ---- nodes ----
    def supervisor(state: SupportState) -> dict:
        if state.get("hops", 0) >= MAX_HOPS:
            return {"next": "FINISH"}
        choice = router(state["messages"])
        return {"next": choice if choice in ROUTES else "FINISH"}

    def _context(state: SupportState) -> list:
        email = state.get("customer_email") or "unknown"
        return [SystemMessage(f"Customer email: {email}")]

    def orders_node(state: SupportState) -> dict:
        result = orders_agent.invoke({"messages": _context(state) + state["messages"]})
        return {
            "messages": [AIMessage(content=_last_text(result), name="orders")],
            "hops": state.get("hops", 0) + 1,
        }

    def faq_node(state: SupportState) -> dict:
        result = faq_agent.invoke({"messages": state["messages"]})
        return {
            "messages": [AIMessage(content=_last_text(result), name="faq")],
            "hops": state.get("hops", 0) + 1,
        }

    def escalate_node(state: SupportState) -> dict:
        """Create the ticket. Kept separate from human_review because a node that
        calls interrupt() re-runs from the top when resumed (would double-create)."""
        last_customer_msg = next(
            (m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), ""
        )
        ticket = tools.create_escalation_ticket.invoke(
            {"summary": str(last_customer_msg)[:500], "customer_email": state.get("customer_email", "")}
        )
        return {
            "ticket_id": ticket["ticket_id"],
            "messages": [
                AIMessage(
                    content=f"I've escalated this to our support team (ticket #{ticket['ticket_id']}). "
                    "A human agent will reply shortly.",
                    name="escalation",
                )
            ],
            "hops": state.get("hops", 0) + 1,
        }

    def human_review_node(state: SupportState) -> dict:
        """Pause the graph until a human agent supplies a reply (human-in-the-loop)."""
        reply = interrupt({"ticket_id": state["ticket_id"], "question": "Human agent reply needed"})
        tools.resolve_ticket(state["ticket_id"], str(reply))
        return {
            "messages": [AIMessage(content=str(reply), name="human_agent")],
            "hops": MAX_HOPS,  # human has answered: stop looping
        }

    # ---- wiring ----
    g = StateGraph(SupportState)
    g.add_node("supervisor", supervisor)
    g.add_node("orders", orders_node)
    g.add_node("faq", faq_node)
    g.add_node("escalation", escalate_node)
    g.add_node("human_review", human_review_node)

    g.add_edge(START, "supervisor")
    g.add_conditional_edges(
        "supervisor",
        lambda s: s["next"],
        {"orders": "orders", "faq": "faq", "escalation": "escalation", "FINISH": END},
    )
    g.add_edge("orders", "supervisor")
    g.add_edge("faq", "supervisor")
    g.add_edge("escalation", "human_review")
    g.add_edge("human_review", "supervisor")

    return g.compile(checkpointer=checkpointer or MemorySaver())
