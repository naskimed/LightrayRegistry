"""Daemon entrypoint (TECH_SPEC §5.3).

Boot: acquire the flock (second daemon fails fast) → verify() the chain → cold replay →
start writer / api / inbox / scheduler / heartbeat → serve until signal.
"""
from __future__ import annotations

import signal
import threading
import time

from .. import config
from ..ledger import Ledger, verify
from ..reducer import replay
from ..store import write_json_atomic
from .agents import AgentRunner
from .api import Api
from .inbox import InboxPoller
from .lock import registry_flock
from .scheduler import Scheduler
from .writer import Writer


class Heartbeat(threading.Thread):
    """daemon.status.json every 10 s — liveness is NOT an event."""

    def __init__(self, writer: Writer):
        super().__init__(name="heartbeat", daemon=True)
        self.writer = writer
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.is_set():
            s = self.writer.state
            write_json_atomic(config.status_path(), {
                "pid_alive": True, "ts": time.time(),
                "as_of_seq": s.as_of_seq, "head": s.head_hash,
                "open_cycle": s.open_cycle,
                "halt": config.halt_path().exists(),
                "readonly": config.readonly_path().exists(),
                "suspended": bool(s.suspensions.get("readout_conditional_channel")),
            })
            time.sleep(10)


def main() -> int:
    config.ensure_layout()
    with registry_flock():
        ledger = Ledger(writable=True)       # holds the flock; drops a torn tail on construction
        v = verify()
        if not v.ok:
            print(f"REFUSING TO START: chain verify failed at seq {v.first_bad_seq}: {v.reason}")
            return 1
        state = replay(ledger.iter_events())
        print(f"replayed {state.as_of_seq + 1} events · head {state.head_hash[:16]}")

        writer = Writer(ledger, state)
        agents = AgentRunner()
        sched = Scheduler(writer, agent_runner=agents)
        api = Api(writer)
        inbox = InboxPoller(writer)
        hb = Heartbeat(writer)

        for t in (writer, sched, api, inbox, hb):
            t.start()
        print(f"daemon up · http://{config.API_HOST}:{config.API_PORT} · workdir {config.workdir()}")

        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        while not stop.is_set():
            time.sleep(1)

        print("shutting down…")
        for t in (sched, inbox, hb, writer):
            t.stop()
        api.stop()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
