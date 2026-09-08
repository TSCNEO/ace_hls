import os
import tempfile
import datetime
import pytest

from app.services.agenda_service import (
    AgendaService,
    canonical_tokens,
    extract_stream_quality,
)

SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<body>
<table class="tablaPrincipal">
  <tr class="cabeceraTabla">
    <td colspan="5">Partidos de hoy martes, 08/09/2026</td>
  </tr>
  <tr>
    <td class="hora">21:00</td>
    <td class="detalles">
      <div class="contenedorImgCompeticion">
        <img src="/img/laliga.png" />
      </div>
      <div class="ajusteDoslineas" title="LaLiga EA Sports | Jornada 5">
        <label title="LaLiga EA Sports">LaLiga EA Sports</label>
      </div>
    </td>
    <td class="evento">
      <div class="local"><span title="Real Madrid">Real Madrid</span></div>
      <div class="visitante"><span title="Barcelona">Barcelona</span></div>
    </td>
    <td class="canales">
      <ul class="listaCanales">
        <li title="M+ LALIGA (M54 O110)">M+ LALIGA</li>
        <li title="DAZN LaLiga (M55 O113)">DAZN LaLiga</li>
        <li title="RTVE Play">RTVE Play</li>
      </ul>
    </td>
  </tr>
  <tr>
    <td class="hora">22:30</td>
    <td class="detalles">
      <div class="ajusteDoslineas" title="Fórmula 1">Fórmula 1</div>
    </td>
    <td class="evento">
      <div class="eventoUnico">Clasificación GP Monza</div>
    </td>
    <td class="canales">
      <ul class="listaCanales">
        <li title="DAZN 1 (M70)">DAZN 1</li>
      </ul>
    </td>
  </tr>
</table>
<table class="tablaPrincipal">
  <tr class="cabeceraTabla">
    <td colspan="5">Mañana miércoles, 09/09/2026</td>
  </tr>
  <tr>
    <td class="hora">19:00</td>
    <td class="detalles">
      <div class="ajusteDoslineas" title="Champions League">Champions League</div>
    </td>
    <td class="evento">
      <div class="local"><span title="PSG">PSG</span></div>
      <div class="visitante"><span title="Bayern">Bayern</span></div>
    </td>
    <td class="canales">
      <ul class="listaCanales">
        <li title="M+ Liga de Campeones 2 (M61 O117)">M+ Liga de Campeones 2</li>
      </ul>
    </td>
  </tr>
</table>
</body>
</html>
"""


def test_quality_extraction():
    assert extract_stream_quality("M+ LaLiga 1080p *") == "1080p"
    assert extract_stream_quality("DAZN 1 FHD ad6d --> NEW ERA") == "1080p"
    assert extract_stream_quality("LaLiga TV Hypermotion 720p **") == "720p"
    assert extract_stream_quality("Eurosport 4K") == "4K"
    assert extract_stream_quality("🔹Dazn La Liga ★") == "SD"


def test_canonical_tokens():
    tokens1 = canonical_tokens("M+ LALIGA (M54 O110)")
    assert "movistar" in tokens1
    assert "la" in tokens1 and "liga" in tokens1
    assert "m54" not in tokens1

    tokens2 = canonical_tokens("M+ Liga de Campeones 2 1080p *")
    assert "2" in tokens2
    assert "1080p" not in tokens2

    tokens3 = canonical_tokens("DAZN 1 FHD ad6d --> NEW ERA")
    assert "1" in tokens3
    assert "new" not in tokens3 and "era" not in tokens3


def test_parse_agenda_html():
    service = AgendaService()
    days = service.parse_agenda_html(SAMPLE_HTML)
    assert len(days) == 2

    # Day 1
    d1 = days[0]
    assert d1["date"] == "08/09/2026"
    assert d1["events_count"] == 2

    ev1 = d1["events"][0]
    assert ev1["time"] == "21:00"
    assert ev1["event"] == "Real Madrid - Barcelona"
    assert "LaLiga EA Sports" in ev1["competition"]
    # RTVE Play should be excluded by default filters
    assert "RTVE Play" not in ev1["channels"]
    assert "M+ LALIGA (M54 O110)" in ev1["channels"]
    assert "DAZN LaLiga (M55 O113)" in ev1["channels"]

    # Day 2
    d2 = days[1]
    assert d2["date"] == "09/09/2026"
    assert d2["events_count"] == 1
    assert d2["events"][0]["event"] == "PSG - Bayern"


def test_strict_number_channel_matching():
    service = AgendaService()
    equivs = service.load_equivalencias()

    catalog = [
        {"name": "M+ Liga de Campeones 1080p *", "stream_id": "champ_1_1080"},
        {"name": "M+ Liga de Campeones 2 720p *", "stream_id": "champ_2_720"},
        {"name": "M+ Liga de Campeones 2 1080p *", "stream_id": "champ_2_1080"},
        {"name": "DAZN 1 FHD", "stream_id": "dazn_1_fhd"},
        {"name": "DAZN 2 1080p", "stream_id": "dazn_2_1080"},
    ]

    # Matching "M+ Liga de Campeones 2 (M61 O117)" must ONLY match champ_2, NOT champ_1
    m2 = service.match_channel_to_catalog("M+ Liga de Campeones 2 (M61 O117)", catalog, equivs)
    matched_ids2 = [item["stream_id"] for item in m2]
    assert "champ_2_1080" in matched_ids2
    assert "champ_2_720" in matched_ids2
    assert "champ_1_1080" not in matched_ids2

    # Matching "M+ Liga de Campeones (M60 O115)" must ONLY match champ_1, NOT champ_2
    m1 = service.match_channel_to_catalog("M+ Liga de Campeones (M60 O115)", catalog, equivs)
    matched_ids1 = [item["stream_id"] for item in m1]
    assert "champ_1_1080" in matched_ids1
    assert "champ_2_1080" not in matched_ids1

    # Matching DAZN 1
    dazn1 = service.match_channel_to_catalog("DAZN 1 (M70)", catalog, equivs)
    dazn1_ids = [item["stream_id"] for item in dazn1]
    assert "dazn_1_fhd" in dazn1_ids
    assert "dazn_2_1080" not in dazn1_ids


def test_get_agenda_enrichment_and_caching(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        service = AgendaService(data_dir=tmpdir)
        monkeypatch.setattr(service, "fetch_raw_agenda", lambda: SAMPLE_HTML)

        catalog = [
            {"name": "M+ LaLiga 1080p **", "stream_id": "stream_laliga_1080", "source_name": "Fuente A"},
            {"name": "M+ LaLiga 720p *", "stream_id": "stream_laliga_720", "source_name": "Fuente B"},
        ]

        agenda = service.get_agenda(catalog_channels=catalog, force_refresh=True)
        assert agenda["total_events"] == 3
        assert agenda["available_events"] == 1  # Only Real Madrid vs Barcelona matched

        # Cache file must exist
        assert os.path.exists(service.cache_file)

        # Inspect first event
        d1 = agenda["days"][0]
        ev_clasico = d1["events"][0]
        assert ev_clasico["available"] is True
        assert ev_clasico["streams_count"] == 2
        assert ev_clasico["primary_stream_id"] == "stream_laliga_1080"
        # First stream must be 1080p
        assert ev_clasico["streams"][0]["quality"] == "1080p"


def test_generate_agenda_m3u(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        service = AgendaService(data_dir=tmpdir)
        monkeypatch.setattr(service, "fetch_raw_agenda", lambda: SAMPLE_HTML)

        catalog = [
            {"name": "M+ LaLiga 1080p **", "stream_id": "stream_laliga_1080", "source_name": "Fuente A"},
            {"name": "M+ LaLiga 720p *", "stream_id": "stream_laliga_720", "source_name": "Fuente B"},
        ]

        # 1. Standard single-profile M3U
        m3u_text = service.generate_agenda_m3u(
            host="127.0.0.1:8088",
            profile="original",
            catalog_channels=catalog,
        )
        assert m3u_text.startswith("#EXTM3U")
        assert "Real Madrid - Barcelona (1080p · Fuente A)" in m3u_text
        assert "Real Madrid - Barcelona (720p · Fuente B)" in m3u_text
        assert "http://127.0.0.1:8088/stream/stream_laliga_1080.m3u8" in m3u_text

        # 2. Multi-surface "all" profile M3U
        m3u_all = service.generate_agenda_m3u(
            host="127.0.0.1:8088",
            profile="all",
            catalog_channels=catalog,
        )
        assert 'group-title="⚽ Hoy · Directo"' in m3u_all
        assert 'group-title="⚽ Hoy · HLS Original"' in m3u_all
        assert 'group-title="⚽ Hoy · HLS 720p"' in m3u_all

        # 3. XMLTV Generation
        xmltv_text = service.generate_xmltv(catalog_channels=catalog)
        assert xmltv_text.startswith('<?xml version="1.0" encoding="UTF-8"?>')
        assert '<tv generator-info-name="AceHLS">' in xmltv_text
        assert 'channel id="stream_laliga_1080"' in xmltv_text
        assert '<programme ' in xmltv_text
        assert '<title lang="es">Real Madrid - Barcelona</title>' in xmltv_text
        assert '<category lang="es">Deportes</category>' in xmltv_text
        assert '</tv>' in xmltv_text


def test_probe_candidate_streams():
    service = AgendaService()

    candidates = [
        {"stream_id": "stream_1", "quality": "1080p", "source_name": "S1"},
        {"stream_id": "stream_2", "quality": "1080p", "source_name": "S2"},
        {"stream_id": "stream_3", "quality": "720p", "source_name": "S3"},
        {"stream_id": "stream_4", "quality": "SD", "source_name": "S4"},
    ]

    probed_calls = []

    def mock_probe_fn(stream_id, itype):
        probed_calls.append(stream_id)
        # stream_1 and stream_2 are live
        return stream_id in ("stream_1", "stream_2")

    result = service.probe_candidate_streams(
        candidates,
        max_candidates=3,
        stop_at_live=2,
        probe_fn=mock_probe_fn,
    )

    assert result["status"] == "ok"
    assert result["live_count"] == 2
    assert "stream_1" in result["probed"]
    assert result["probed"]["stream_1"]["alive"] is True
    assert "stream_2" in result["probed"]
    assert result["probed"]["stream_2"]["alive"] is True
    # Stopped as soon as 2 live streams were found, stream_3 and stream_4 were never called
    assert "stream_3" not in result["probed"]
    assert probed_calls == ["stream_1", "stream_2"]


def test_calculate_live_status_and_soon():
    service = AgendaService()
    now = datetime.datetime.now()

    # Event in 10 minutes (soon)
    t_soon = now + datetime.timedelta(minutes=10)
    is_live, is_up, diff, is_soon = service._calculate_live_status(
        t_soon.strftime("%d/%m/%Y"), t_soon.strftime("%H:%M")
    )
    assert is_soon is True
    assert 8 <= diff <= 12

    # Event in 3 hours (not soon)
    t_far = now + datetime.timedelta(hours=3)
    is_live_far, is_up_far, diff_far, is_soon_far = service._calculate_live_status(
        t_far.strftime("%d/%m/%Y"), t_far.strftime("%H:%M")
    )
    assert is_soon_far is False
    assert diff_far >= 150


def test_discard_events_older_than_4_hours(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        service = AgendaService(data_dir=tmpdir)
        now = datetime.datetime.now()

        # Event 5 hours ago (older than 4h) -> should be discarded
        t_old = now - datetime.timedelta(hours=5)
        # Event 3 hours ago (finished, >135m, but within 4h) -> should be kept as is_past
        t_recent = now - datetime.timedelta(hours=3)
        # Event in 2 hours -> should be kept as future
        t_future = now + datetime.timedelta(hours=2)

        fake_days = [{
            "date": now.strftime("%d/%m/%Y"),
            "title": "Hoy",
            "events": [
                {"time": t_old.strftime("%H:%M"), "event": "Old Event", "channels": []},
                {"time": t_recent.strftime("%H:%M"), "event": "Recent Event", "channels": []},
                {"time": t_future.strftime("%H:%M"), "event": "Future Event", "channels": []},
            ]
        }]

        service._memory_cache = {"days": fake_days, "updated_at": "now"}
        service._memory_cache_time = datetime.datetime.now().timestamp()
        result = service.get_agenda(catalog_channels=[])

        events_kept = result["days"][0]["events"]
        assert len(events_kept) == 2
        titles = [e["event"] for e in events_kept]
        assert "Old Event" not in titles
        assert "Recent Event" in titles
        assert "Future Event" in titles
        # Check is_past
        recent_ev = next(e for e in events_kept if e["event"] == "Recent Event")
        assert recent_ev["is_past"] is True
        future_ev = next(e for e in events_kept if e["event"] == "Future Event")
        assert future_ev["is_past"] is False
