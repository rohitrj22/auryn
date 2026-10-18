"""Integrating Auryn into an agent you already have.

A deliberately different domain from the demo: a meal-planning assistant.
The engine is unchanged. Nothing about it knows what a meal is.

Run:  uv run python examples/bring_your_own_agent.py
"""

from auryn import Memory, EVENT, PROCEDURE, FACT

# --------------------------------------------------------------------------
# YOUR CODE. Auryn never sees inside this. Replace it with any model call:
# OpenAI, Anthropic, Gemini, Ollama, or a local model.
# --------------------------------------------------------------------------


def your_model(system: str, user_message: str) -> str:
    """Stand-in for your real model call. Your prompts, your client, your keys."""
    return f"(model reply using: {system[:70]}...)"


# --------------------------------------------------------------------------
# BEFORE AURYN. Works, but forgets everything the moment it returns.
# --------------------------------------------------------------------------


def agent_without_memory(user_message: str) -> str:
    system = "You are a meal planning assistant."
    return your_model(system, user_message)


# --------------------------------------------------------------------------
# AFTER AURYN. Three added lines, marked below.
# --------------------------------------------------------------------------


def agent_with_memory(mem: Memory, session, user_message: str, turn: int) -> str:
    # (1) ADDED. Two calls, not one. standing() carries what always applies;
    # recall() adds what this message is about. An allergy is not something an
    # agent searches for, so it must not depend on the wording of a question.
    context = mem.standing() + mem.recall(user_message)
    context = list({m.id: m for m in context}.values())

    known = "\n".join(f"- [{m.kind}] {m.text}" for m in context) or "nothing yet"
    system = f"You are a meal planning assistant.\nYou remember:\n{known}"

    reply = your_model(system, user_message)                      # your code

    mem.add_turn(session, role="user", text=user_message, idx=turn * 2)
    mem.add_turn(session, role="agent", text=reply, idx=turn * 2 + 1)
    return reply


def main() -> None:
    print("=" * 74)
    print("SESSION 1 — a brand new user. The agent knows nothing.")
    print("=" * 74)

    mem = Memory(tenant="user_8812")          # (2) ADDED: one graph for this user
    mem.forget_everything()                   # a clean run for this example
    mem = Memory(tenant="user_8812", consolidate_after=3)

    s1 = mem.start_session(agent="meal-bot")

    print("\nuser : I am allergic to peanuts.")
    print("bot  :", agent_with_memory(mem, s1, "I am allergic to peanuts.", 0)[:70])
    mem.remember(FACT, "allergic to peanuts",                  # (3) ADDED
                 agent="meal-bot", subject="Allergies", session=s1)

    print("\nuser : I skipped dinner again last night.")
    print("bot  :", agent_with_memory(mem, s1, "I skipped dinner again last night.", 1)[:70])
    mem.remember(EVENT, "skipped dinner on a weeknight",
                 agent="meal-bot", subject="Dinner habits", session=s1)

    print("\nuser : Never suggest anything over 600 calories for dinner.")
    print("bot  :", agent_with_memory(mem, s1, "Never over 600 calories for dinner.", 2)[:70])
    mem.remember(PROCEDURE, "keep dinner suggestions under 600 calories",
                 agent="meal-bot", subject="Dinner habits", session=s1,
                 trigger="meal == dinner")

    mem.end_session(s1)

    print("\n" + "=" * 74)
    print("SESSION 2 — days later. A NEW process. No conversation history given.")
    print("=" * 74)

    later = Memory(tenant="user_8812")        # same tenant, fresh object
    s2 = later.start_session(agent="meal-bot")

    standing = later.standing()
    relevant = later.recall("what should I eat for dinner")
    context = list({m.id: m for m in standing + relevant}.values())
    print("\nWhat the agent carried before it said a word:")
    for m in context:
        print(f"   [{m.kind:9}] {m.text}")
    print("   (the allergy came from standing(), not from matching the question)")

    print("\nOnly the lasting rules:")
    for m in later.recall("dinner calories", kind=PROCEDURE):
        print(f"   {m.text}   (applies when {m.trigger})")

    print("\nOnly the hard facts:")
    for m in later.recall("allergy peanuts", kind=FACT):
        print(f"   {m.text}")

    print("\n" + "=" * 74)
    print("A SECOND AGENT joins. It gets no message from the first.")
    print("=" * 74)

    later.create_task("plan-week-42", title="plan next week's dinners",
                      agent="meal-bot", subjects=["Dinner habits", "Allergies"])
    later.handoff("plan-week-42", from_agent="meal-bot", to_agent="shopping-bot",
                  note="build a shopping list")

    # A different process entirely would do exactly this, with two strings.
    shopping = Memory(tenant="user_8812")
    ctx = shopping.pick_up("plan-week-42", agent="shopping-bot")
    print(f"\nshopping-bot received: task={ctx.task!r}, handed_from={ctx.handed_from!r}")
    print("It read this from the graph, with no briefing:")
    for m in ctx.memories:
        print(f"   [{m.kind:9}] {m.text}")

    print("\n" + "=" * 74)
    print("ISOLATION — another user is untouched.")
    print("=" * 74)
    other = Memory(tenant="user_9001"); other.forget_everything()
    other = Memory(tenant="user_9001")
    other.remember(FACT, "vegetarian", agent="meal-bot", subject="Diet")
    print("\nuser_9001 recalls 'peanuts' ->", [m.text for m in other.recall("peanuts allergy")])
    print("user_8812 recalls 'vegetarian' ->", [m.text for m in later.recall("vegetarian")])
    print("Both empty. The graph boundary makes a leak impossible, not merely forbidden.")

    later.end_session(s2)


if __name__ == "__main__":
    main()
