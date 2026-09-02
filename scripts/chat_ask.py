"""One shopper message through the dispatched door — [ADR-0031].

``care_ask`` and ``sell_ask`` drive one agent's graph in-process, which is what
makes them good at showing *how* that agent thought. This one is the opposite
and deliberately so: it goes over **HTTP, to the running API, with a public
widget key**, so it exercises the thing a browser exercises — the origin lock,
the entitlement check, the scope check, and the dispatcher's choice.

It prints the three things a hand-test needs and a transcript does not show
together:

* **which agent the server chose** — the shopper did not, and neither did you;
* **how the turn ended**, in the shopper's terms;
* **why**, when it ended at a person, in the node's own words.

That third one is the point. "I'm passing you to a colleague" is what a shopper
sees for an authorisation refusal, a verifier catching a mangled number, and a
planner that picked the wrong tool — three unrelated causes wearing one
sentence. Reading it from the outside, they are indistinguishable; this prints
the reason the log recorded.

    make chat-ask KEY=fn_pk_... Q="do you sell jackets?"

The escalation *reason* is not in the reply and is not meant to be: it is
written for the merchant, and it appears in the API's own log.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import httpx

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"

#: How a turn ended, in the words a shopper would use for it.
OUTCOMES = {
    "resolved": (GREEN, "answered"),
    "escalated": (YELLOW, "handed to a person"),
    "blocked": (RED, "blocked"),
}


def ask(
    base: str,
    key: str,
    message: str,
    conversation_id: str | None,
    customer: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"message": message}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    if customer:
        # **Refused on a public key, in the route.** A browser cannot be trusted
        # to name its own customer, so this only works with a secret key — which
        # is the merchant's server speaking, not a shopper's tab. Passing it here
        # is how the *other* half of the ownership gate gets exercised by hand:
        # the same order number that escalates anonymously is answered for the
        # customer who owns it, and returns nothing for one who does not.
        payload["customer"] = {"external_id": customer}

    origin = base.rstrip("/")
    try:
        response = httpx.post(
            f"{origin}/v1/chat",
            json=payload,
            headers={
                "Authorization": f"Bearer {key}",
                # The key is origin-locked (ADR-0014 §3), so a request without
                # this is refused before any model runs — the control working,
                # not something to route around.
                "Origin": origin,
            },
            timeout=600,
        )
    except httpx.HTTPError as exc:
        raise SystemExit(f"  cannot reach {base} — {exc}\n  Is the API running?") from exc

    try:
        return dict(response.json())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"  {base} did not answer with JSON:\n  {response.text[:400]}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask the dispatched endpoint one question.")
    parser.add_argument("--base", default="http://localhost:8010")
    parser.add_argument("--key", required=True, help="a public widget key (fn_pk_...)")
    parser.add_argument("--conversation", default=None, help="continue an existing conversation")
    parser.add_argument(
        "--as-customer",
        default=None,
        help="a verified customer id — needs a SECRET key (fn_sk_), refused on a public one",
    )
    parser.add_argument("message", nargs="+")
    args = parser.parse_args()

    message = " ".join(args.message)
    who = f"  {DIM}as customer {args.as_customer}{RESET}" if args.as_customer else ""
    print(f"\n{DIM}>{RESET} {BOLD}{message}{RESET}{who}\n")

    body = ask(args.base, args.key, message, args.conversation, args.as_customer)

    error = body.get("error")
    if isinstance(error, dict):
        print(f"  {RED}{error.get('code')}{RESET}")
        print(f"  {error.get('message')}\n")
        return 1

    data = body.get("data")
    if not isinstance(data, dict):
        raise SystemExit(f"  unexpected response shape:\n  {body}")
    state = str(data.get("state", "?"))
    colour, plain = OUTCOMES.get(state, (DIM, state))

    print(f"  agent    {BOLD}{data.get('agent')}{RESET}   {DIM}← the server chose this{RESET}")
    print(f"  outcome  {colour}{plain}{RESET}")
    if citations := data.get("citations"):
        print(f"  used     {DIM}{[c.get('id') for c in citations]}{RESET}")
    if products := data.get("products"):
        print(f"  cards    {[p.get('title') for p in products]}")
    print(f"  conv     {DIM}{data.get('conversation_id')}{RESET}")

    reply = str(data.get("reply") or data.get("fallback_message") or "(nothing)")
    print("\n  " + reply.replace("\n", "\n  ") + "\n")

    if state == "escalated":
        # The reason is deliberately not in this payload. It is written by a
        # node for a human on the merchant's side, and a shopper's browser is
        # the wrong place for "the planner chose the wrong tool" — so it lives
        # in the API's log and the console's review queue, not here.
        print(
            f"  {DIM}That sentence is the handover, not an error. Three unrelated causes\n"
            f"  wear it — an authorisation refusal, a verifier catching a bad claim,\n"
            f"  and a planner picking the wrong tool.\n\n"
            f"  Which one it was is in the API's own terminal, on the line that\n"
            f"  reads `escalated ... reason=`. It is not in this reply on purpose:\n"
            f"  it is written for the merchant, not for the shopper.{RESET}\n"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
