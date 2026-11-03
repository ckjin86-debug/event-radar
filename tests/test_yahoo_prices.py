from datetime import date

from event_radar.prices.yahoo import YahooPriceProvider


CSV_BODY = """Date,Open,High,Low,Close,Adj Close,Volume
2026-10-30,100,102,99,101,101,123456
"""


def test_korean_ticker_falls_back_from_kospi_to_kosdaq(monkeypatch):
    provider = YahooPriceProvider(max_retries=0)
    called_urls: list[str] = []

    class MockResponse:
        def __init__(self, status_code: int, text: str):
            self.status_code = status_code
            self.text = text

    def mock_get(url, timeout=10):
        called_urls.append(url)
        if "/259960.KS?" in url:
            return MockResponse(404, "")
        if "/259960.KQ?" in url:
            return MockResponse(200, CSV_BODY)
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(provider.session, "get", mock_get)

    df = provider.history("259960", date(2026, 10, 30), date(2026, 10, 30))

    assert len(df) == 1
    assert df.iloc[0]["adj_close"] == 101
    assert any("/259960.KS?" in url for url in called_urls)
    assert any("/259960.KQ?" in url for url in called_urls)
