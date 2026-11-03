import io
import zipfile

from event_radar.entities import EntityUniverse, parse_dart_corp_code_zip


def test_dart_official_english_name_resolves_latin_headline_alias():
    xml = b"""<?xml version='1.0' encoding='UTF-8'?>
    <result>
      <list>
        <corp_name>\xec\x97\x98\xec\xa7\x80\xec\x94\xa8\xec\x97\x94\xec\x97\x90\xec\x8a\xa4</corp_name>
        <corp_eng_name>LG CNS CO., LTD.</corp_eng_name>
        <stock_code>064400</stock_code>
      </list>
    </result>
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("CORPCODE.xml", xml)

    universe = EntityUniverse(parse_dart_corp_code_zip(buf.getvalue()))
    matches = universe.resolve_mentions("LG CNS, 인니 데이터센터 내달 준공", "KR")

    assert [match.ticker for match in matches] == ["064400"]
