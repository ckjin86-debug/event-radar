import threading
import time

from event_radar import ipo_enrichment as mod


class _Response:
    status_code = 200

    def json(self):
        return {"items": []}


def test_ipo_relation_prefetch_dedupes_companies_and_runs_concurrently(monkeypatch):
    lock = threading.Lock()
    active = 0
    max_active = 0
    calls = []

    def fake_get(*args, **kwargs):
        nonlocal active, max_active
        company = kwargs["params"]["query"]
        with lock:
            calls.append(company)
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return _Response()

    monkeypatch.setattr(mod.requests, "get", fake_get)
    enricher = mod.IpoRelationEnricher(api_key_id="id", api_key="key", max_workers=4)

    enricher.prefetch(["래블업", "이에스티", "래블업", "동원파츠"])

    assert sorted(calls) == ["동원파츠", "래블업", "이에스티"]
    assert max_active >= 2
    assert enricher._fetch_payloads("래블업") == [{"items": []}]
    assert calls.count("래블업") == 1
