from datetime import date

from event_radar.prices.yahoo import YahooPriceProvider


CHART_BODY = {
    "chart": {
        "result": [
            {
                "timestamp": [1793318400],
                "indicators": {
                    "quote": [
                        {
                            "open": [100.0],
                            "high": [102.0],
                            "low": [99.0],
                            "close": [101.0],
                            "volume": [123456],
                        }
                    ],
                    "adjclose": [{"adjclose": [101.0]}],
                },
            }
        ],
        "error": None,
    }
}


def test_korean_ticker_falls_back_from_kospi_to_kosdaq_with_chart_api(monkeypatch):
    provider = YahooPriceProvider(max_retries=0)
    called_urls: list[str] = []

    class MockResponse:
        def __init__(self, status_code: int, payload: dict):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    def mock_get(url, timeout=10):
        called_urls.append(url)
        if "/chart/259960.KS?" in url:
            return MockResponse(404, {})
        if "/chart/259960.KQ?" in url:
            return MockResponse(200, CHART_BODY)
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(provider.session, "get", mock_get)

    df = provider.history("259960", date(2026, 10, 30), date(2026, 10, 30))

    assert len(df) == 1
    assert df.iloc[0]["adj_close"] == 101
    assert any("/chart/259960.KS?" in url for url in called_urls)
    assert any("/chart/259960.KQ?" in url for url in called_urls)


def test_chart_parser_skips_null_price_rows(monkeypatch):
    provider = YahooPriceProvider(max_retries=0)
    payload = {
        "chart": {
            "result": [{
                "timestamp": [1793318400, 1793404800],
                "indicators": {
                    "quote": [{
                        "open": [100.0, None],
                        "high": [102.0, None],
                        "low": [99.0, None],
                        "close": [101.0, None],
                        "volume": [123456, None],
                    }],
                    "adjclose": [{"adjclose": [101.0, None]}],
                },
            }],
            "error": None,
        }
    }

    class MockResponse:
        status_code = 200
        def json(self):
            return payload

    monkeypatch.setattr(provider.session, "get", lambda url, timeout=10: MockResponse())
    df = provider.history("005930", date(2026, 10, 30), date(2026, 10, 31))

    assert len(df) == 1
    assert df.iloc[0]["close"] == 101.0
