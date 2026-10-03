"""Durable, opt-in MAL polling. No API key means idle, never a fallback scraper."""
import argparse
import logging
import signal
import threading

from database.connection import SessionLocal
from services.personal_anime_sync import configured, due_owners, sync_owner

log = logging.getLogger("personal_anime_worker")


def run_once():
    if not configured():
        return {"configured": False, "checked": 0, "failed": 0}
    with SessionLocal() as db:
        owners = due_owners(db)
    checked, failed = 0, 0
    for owner_id in owners:
        with SessionLocal() as db:
            try:
                sync_owner(db, owner_id, scheduled=True)
                checked += 1
            except Exception:
                # No provider payloads, usernames, tokens or private list data in logs.
                db.rollback()
                failed += 1
                log.warning("A private MAL sync did not complete; prior snapshots retained.")
    return {"configured": True, "checked": checked, "failed": failed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    stopped = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopped.set())
    while not stopped.is_set():
        try:
            result = run_once()
            if args.once or result["checked"] or result["failed"]:
                log.info("MAL polling: %s", result)
        except Exception:
            log.error("MAL worker check failed; retrying on the next sweep.")
        if args.once:
            return
        stopped.wait(60)


if __name__ == "__main__":
    main()
