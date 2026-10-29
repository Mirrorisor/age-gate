"""The invoice store keeps its record in a SQLite file, so a restart does not forget payments."""

import sqlite3
import threading
import time

from agecheck.zecpay import InvoiceStore


def test_invoice_survives_reopen(tmp_path):
    path = str(tmp_path / "inv.db")
    first = InvoiceStore(path)
    first.add("i1", 100000, "zcash:u1?amount=0.001", "u1")
    again = InvoiceStore(path)
    record = again.get("i1")
    assert record["status"] == "pending"
    assert record["amount_zat"] == 100000
    assert record["payment_uri"] == "zcash:u1?amount=0.001"
    assert record["address"] == "u1"
    assert not again.is_paid("i1")


def test_paid_survives_reopen_and_stays_final(tmp_path):
    path = str(tmp_path / "inv.db")
    first = InvoiceStore(path)
    first.add("i1", 100, "zcash:u1", "u1")
    first.record("i1", "e1", 5, "paid")
    again = InvoiceStore(path)
    assert again.is_paid("i1")
    again.record("i1", "e2", 6, "expired")
    assert again.get("i1")["status"] == "paid"


def test_replayed_and_older_events_still_refused_after_reopen(tmp_path):
    path = str(tmp_path / "inv.db")
    first = InvoiceStore(path)
    first.add("i1", 100, "zcash:u1", "u1")
    first.record("i1", "e1", 3, "detected")
    again = InvoiceStore(path)
    assert not again.is_new_event("i1", "e1", 9)  # same event id
    assert not again.is_new_event("i1", "e2", 3)  # not newer than seq 3
    assert again.is_new_event("i1", "e3", 4)


def test_unknown_invoice_and_odd_ids(tmp_path):
    store = InvoiceStore(str(tmp_path / "inv.db"))
    assert store.get("missing") is None
    assert store.get(None) is None and store.get(["x"]) is None
    assert not store.is_paid("missing")
    assert not store.is_new_event("missing", "e1", 1)
    store.record("missing", "e1", 1, "paid")  # silently ignored
    assert store.get("missing") is None


def test_adding_an_id_again_starts_it_fresh(tmp_path):
    store = InvoiceStore(str(tmp_path / "inv.db"))
    store.add("i1", 100, "zcash:u1", "u1")
    store.record("i1", "e1", 2, "detected")
    store.add("i1", 100, "zcash:u1", "u1")
    assert store.get("i1")["status"] == "pending"
    assert store.is_new_event("i1", "e1", 1)


def test_memory_stores_are_separate_from_each_other_and_from_files(tmp_path):
    a, b = InvoiceStore(), InvoiceStore()
    a.add("i1", 1, "zcash:x", "x")
    assert b.get("i1") is None
    assert not (tmp_path / "inv.db").exists()


def test_two_threads_can_write_at_once(tmp_path):
    store = InvoiceStore(str(tmp_path / "inv.db"))

    def work(n):
        for k in range(20):
            store.add(f"i{n}-{k}", k, "zcash:x", "x")
            store.record(f"i{n}-{k}", "e", k, "paid")

    threads = [threading.Thread(target=work, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(store.is_paid(f"i{n}-{k}") for n in range(4) for k in range(20))


def test_sequence_number_never_goes_backwards(tmp_path):
    store = InvoiceStore(str(tmp_path / "inv.db"))
    store.add("i1", 100, "zcash:u1", "u1")
    store.record("i1", "e1", 5, "detected")
    store.record("i1", "e2", 3, "detected")
    assert store.get("i1")["seq"] == 5


def test_old_invoices_and_their_events_are_pruned(tmp_path):
    store = InvoiceStore(str(tmp_path / "inv.db"))
    store.add("old", 100, "zcash:u1", "u1")
    store.record("old", "e1", 1, "paid")
    store.add("new", 100, "zcash:u2", "u2")
    later = time.time() + 31 * 86400
    store.record("new", "e2", 1, "detected")
    removed = store.prune(30 * 86400, now=later)
    assert removed == 2  # both are older than 30 days at `later`
    assert store.get("old") is None and store.get("new") is None
    store.add("old", 100, "zcash:u1", "u1")
    assert store.is_new_event("old", "e1", 1)  # its events went too


def test_recent_invoices_are_kept(tmp_path):
    store = InvoiceStore(str(tmp_path / "inv.db"))
    store.add("i1", 100, "zcash:u1", "u1")
    assert store.prune(30 * 86400) == 0
    assert store.get("i1") is not None


def test_a_file_from_before_pruning_is_upgraded(tmp_path):
    path = str(tmp_path / "inv.db")
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE invoices (id TEXT PRIMARY KEY, status TEXT NOT NULL, "
        "amount_zat TEXT NOT NULL, payment_uri TEXT NOT NULL, address TEXT NOT NULL, "
        "seq INTEGER NOT NULL)"
    )
    db.execute("INSERT INTO invoices VALUES ('i1', 'paid', '100', 'zcash:u1', 'u1', 3)")
    db.commit()
    db.close()
    store = InvoiceStore(path)
    assert store.is_paid("i1")
    assert store.prune(30 * 86400) == 0
    assert store.prune(30 * 86400, now=time.time() + 31 * 86400) == 1
