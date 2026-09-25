"""A built-in "Demo CRM", so tools can be tried with no account anywhere.

Connected as `builtin://demo`: it runs in this process, touches no network,
and answers from made-up data that is the same every time — the same phone
number is always the same customer, the same date always has the same free
slots — so a rehearsal can be repeated and a test can assert on it. Nothing is
stored: booking a slot does not take it.
"""

from __future__ import annotations

import datetime
import hashlib

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

DEMO_URL = "builtin://demo"

_FIRST_NAMES = ("Asha", "Rahul", "Priya", "Arjun", "Meera", "Kabir", "Sara", "Dev")
_LAST_NAMES = ("Rao", "Sharma", "Iyer", "Khan", "Patel", "Singh", "Das", "Mehta")
_PLANS = ("Basic", "Plus", "Premium")
_DAY_SLOTS = ("09:30", "11:00", "14:00", "16:30")
_PRIORITIES = ("low", "normal", "high", "urgent")


def demo_server() -> MCPServer:
    server = MCPServer(
        "Demo CRM",
        instructions="A demo CRM with made-up customers, appointment slots and tickets.",
    )

    @server.tool()
    def lookup_customer(phone: str) -> dict:
        """Find the customer on file for a phone number."""
        digits = "".join(ch for ch in phone if ch.isdigit())
        if len(digits) < 6:
            raise ToolError("That doesn't look like a phone number.")
        seed = _seed(digits)
        return {
            "customer_id": f"CUS-{seed % 100000:05d}",
            "name": f"{_FIRST_NAMES[seed % 8]} {_LAST_NAMES[(seed // 8) % 8]}",
            "phone": phone,
            "plan": _PLANS[seed % 3],
            "customer_since": str(2018 + seed % 7),
            "open_tickets": seed % 3,
        }

    @server.tool()
    def check_availability(date: str) -> dict:
        """Free appointment slots on a date (YYYY-MM-DD), as HH:MM times."""
        return {"date": date, "free_slots": _free_slots(_parse_date(date))}

    @server.tool()
    def book_appointment(name: str, date: str, time: str) -> dict:
        """Book an appointment for a person on a date (YYYY-MM-DD) at a free time (HH:MM)."""
        day = _parse_date(date)
        free = _free_slots(day)
        if time not in free:
            offer = ", ".join(free) or "none that day"
            raise ToolError(f"{time} is not free on {date}. Free slots: {offer}.")
        return {
            "appointment_id": f"APT-{_seed(f'{name}|{date}|{time}') % 1000000:06d}",
            "name": name,
            "date": date,
            "time": time,
            "status": "confirmed",
        }

    @server.tool()
    def create_ticket(summary: str, priority: str = "normal") -> dict:
        """Open a support ticket. Priority is low, normal, high or urgent."""
        if priority not in _PRIORITIES:
            raise ToolError(f"Priority must be one of: {', '.join(_PRIORITIES)}.")
        return {
            "ticket_id": f"TKT-{_seed(summary) % 1000000:06d}",
            "summary": summary,
            "priority": priority,
            "status": "open",
        }

    return server


def _seed(text: str) -> int:
    # hashlib, not hash(): hash() of a string changes from one process to the next.
    return int(hashlib.sha256(text.encode()).hexdigest()[:12], 16)


def _parse_date(text: str) -> datetime.date:
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        raise ToolError("Dates must be written YYYY-MM-DD.") from None


def _free_slots(day: datetime.date) -> list[str]:
    if day.weekday() >= 5:
        return []  # closed at weekends
    # One slot a day is already taken, a different one depending on the date.
    taken = _DAY_SLOTS[day.toordinal() % len(_DAY_SLOTS)]
    return [slot for slot in _DAY_SLOTS if slot != taken]
