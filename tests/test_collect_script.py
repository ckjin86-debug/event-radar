from scripts import collect as collect_script


def test_build_collectors_uses_live_dart_and_sec_sources(tmp_path):
    assert hasattr(collect_script, "build_collectors")

    collectors = collect_script.build_collectors(tmp_path)
    by_name = {collector.source_name: collector for collector in collectors}

    assert by_name["DART"].fixture_path is None
    assert by_name["SEC"].fixture_path is None
