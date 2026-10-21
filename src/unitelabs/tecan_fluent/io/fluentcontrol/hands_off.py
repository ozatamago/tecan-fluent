"""Hands-off: another robot (or a person) works on the deck, so the Fluent must not move (docs/deck_state_spec.md).

Begin takes the lock shared by every server on the Fluent PC (shared_lock.py) on behalf of the robot and keeps it, so
every server refuses FluentControl commands with "hands-off by <who> (<reason>, since ...)" until End. It is refused
while a run is open or anything is being sent to FluentControl. MaxMinutes bounds it: after that it is released with
a warning in the log and the records, so a robot that died does not block the Fluent forever. A small background task
of the holding server does this (every check also looks at the clock); the operating system releases the lock anyway
when that server process ends.

Without a shared lock (fluent.shared_lock empty) only this server refuses. Begin, End and the release after MaxMinutes
are recorded in ``OFML\\records\\hands_off\\<time>_<event>.json``.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import secrets
import time

from .errors import BackendError

logger = logging.getLogger(__name__)


class HandsOff:
    def __init__(self, backend, max_minutes: float = 30.0, clock=time.time):
        self.backend = backend
        """The FluentControlBackend of this server (its shared lock, open run and current operation)."""
        self.max_minutes = max_minutes
        """Default and upper limit of MaxMinutes (setting deck.hands_off_max_minutes)."""
        self.clock = clock
        self._held: dict | None = None
        self._watch: asyncio.Task | None = None

    def _stamp(self, t: float) -> str:
        return datetime.datetime.fromtimestamp(t).isoformat(timespec="seconds")

    @property
    def text(self) -> str:
        """'hands-off by <who> (<reason>, since ...)' while this server holds it, else ""."""
        self.expire_if_due()
        h = self._held
        return f"hands-off by {h['who']} ({h['reason']}, since {h['since']})" if h else ""

    def check(self) -> None:
        """Refuse (BackendError) while hands-off is held by this server."""
        text = self.text
        if text:
            raise BackendError(text)

    def state(self) -> str:
        """Who holds hands-off, why, since and until when (also when another server holds it); "" when free."""
        own = self.text
        if own:
            return f"{own}, until {self._held['until']}"
        other = self.backend.other_server()
        return other if other.startswith("hands-off by") else ""

    def begin(self, who: str, reason: str, max_minutes: float = 0) -> str:
        """Take the shared lock on behalf of who and keep it. Returns the token End needs."""
        who, reason = who.strip(), reason.strip()
        if not who:
            raise BackendError("Who must not be empty")
        minutes = float(max_minutes) if max_minutes and max_minutes > 0 else self.max_minutes
        if minutes > self.max_minutes:
            raise BackendError(f"MaxMinutes is at most {self.max_minutes:g} (setting deck.hands_off_max_minutes)")
        if self.text:
            raise BackendError(f"Already {self.text}")
        if self.backend.run_open:
            raise BackendError(f"A run is open (since {self.backend.run_started}); end it first (RunControl.EndRun)")
        if self.backend.busy:
            raise BackendError(f"Another operation is running ({self.backend.current_operation})")
        now = self.clock()
        info = {
            "who": who,
            "reason": reason,
            "since": self._stamp(now),
            "until": self._stamp(now + minutes * 60),
            "max_minutes": minutes,
        }
        if self.backend.shared is not None:  # refuses while another server sends to FluentControl
            self.backend.shared.acquire(f"hands-off by {who}", {"hands_off": info})
        token = secrets.token_hex(8)
        self._held = {**info, "token": token, "deadline": now + minutes * 60}
        logger.info("Hands-off by %s (%s) for at most %g minutes", who, reason, minutes)
        self._record("begin", info)
        self._start_watch()
        return token

    def end(self, token: str) -> str:
        """Release hands-off. Returns what was held."""
        if not self.text:
            other = self.state()
            raise BackendError("Hands-off is not held by this server" + (f" ({other})" if other else ""))
        if token.strip() != self._held["token"]:
            raise BackendError("Wrong token: hands-off can only be ended with the token Begin returned")
        text = self.text
        self._release("end")
        if self._watch is not None:
            self._watch.cancel()
            self._watch = None
        return text

    def expire_if_due(self) -> bool:
        """Release hands-off once MaxMinutes have passed (with a warning). True if it was released now."""
        if self._held is None or self.clock() < self._held["deadline"]:
            return False
        logger.warning(
            "Hands-off by %s (%s, since %s) was not ended within %g minutes: released",
            self._held["who"],
            self._held["reason"],
            self._held["since"],
            self._held["max_minutes"],
        )
        self._release("expired")
        return True

    def _release(self, event: str) -> None:
        held, self._held = self._held, None
        if self.backend.shared is not None:
            self.backend.shared.release()
        data = {k: v for k, v in held.items() if k not in ("token", "deadline")}
        self._record(event, {**data, "released": self._stamp(self.clock())})

    def _record(self, event: str, data: dict) -> None:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
        try:
            self.backend.write_record(f"hands_off\\{stamp}_{event}.json", {"event": event, **data})
        except Exception as exc:  # noqa: BLE001 - the record never decides whether hands-off is held
            logger.warning("Could not record hands-off %s: %s", event, exc)

    def _start_watch(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no event loop (tests): every check still looks at the clock
        self._watch = loop.create_task(self._watch_loop())

    async def _watch_loop(self) -> None:
        while self._held is not None:
            await asyncio.sleep(max(1.0, min(self._held["deadline"] - self.clock(), 30.0)))
            self.expire_if_due()
