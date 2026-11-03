import threading
import time

from event_radar.collectors import news_future as mod


class _Response:
    status_code = 200

    def json(self):
        return {"items": []}


def test_future_news_fetches_queries_concurrently(monkeypatch):
    lock = threading.Lock()
    active = 0
    max_active = 0

    def fake_get(*args, **kwargs):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return _Response()

    monkeypatch.setattr(mod.requests, "get", fake_get)
    collector = mod.NewsFutureCollector(
        api_key_id="id",
        api_key="key",
        queries=["q1", "q2", "q3", "q4"],
        max_workers=4,
    )

    payloads = collector._fetch_payloads()

    assert len(payloads) == 4
    assert max_active >= 2
