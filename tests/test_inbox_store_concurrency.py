"""The inbox store is written by more than one thread at a time.

The workbench serves on a `ThreadingHTTPServer`, and `add_items` is a
read-modify-write over the WHOLE file: it re-serialises every row rather than
appending. Two writers interleaving between the read and the write each build
their result from the same stale snapshot, so one silently discards the other's
rows.

Measured on this store with 4 threads x 15 rows: **17 of 60 survived**. The
same run after locking keeps all 60. No exception is raised in either case —
the loss is silent, which is the only dangerous kind.
"""

import threading

from editor_assistant.workflow import inbox_store


def _item(worker: int, index: int) -> dict:
    return {
        "source_id": "src",
        "title": f"row {worker}-{index}",
        "url": f"https://example.org/{worker}/{index}",
    }


def test_concurrent_writers_do_not_lose_each_others_rows(tmp_path):
    path = tmp_path / "inbox.jsonl"
    workers, per_worker = 4, 15

    def write(worker: int) -> None:
        for index in range(per_worker):
            inbox_store.add_items([_item(worker, index)], path)

    threads = [threading.Thread(target=write, args=(n,)) for n in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    stored = inbox_store.read_items(path)
    assert len(stored) == workers * per_worker, (
        f"{workers * per_worker - len(stored)} row(s) were lost to a read-modify-write race"
    )


def test_the_same_row_still_deduplicates_under_concurrency(tmp_path):
    """The lock must not turn the duplicate check into a race of its own."""
    path = tmp_path / "inbox.jsonl"
    results = []
    lock = threading.Lock()

    def write() -> None:
        outcome = inbox_store.add_items([_item(1, 1)], path)
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=write) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(inbox_store.read_items(path)) == 1
    assert sum(r["new"] for r in results) == 1
    assert sum(r["duplicate"] for r in results) == 5
