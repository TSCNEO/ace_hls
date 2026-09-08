import json
from unittest.mock import patch
from app import create_app
from tests.test_agenda_service import SAMPLE_HTML


def test_api_agenda_routes():
    app = create_app()
    client = app.test_client()

    with patch("app.services.agenda_service.agenda_service.fetch_raw_agenda", return_value=SAMPLE_HTML):
        # 1. GET /api/agenda?refresh=1
        res = client.get("/api/agenda?refresh=1")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert "days" in data
        assert data["total_events"] == 3
        assert len(data["days"]) == 2

        # 2. GET /api/agenda?available_only=1 (when no channels in catalog)
        res_avail = client.get("/api/agenda?available_only=1")
        assert res_avail.status_code == 200
        avail_data = json.loads(res_avail.data)
        assert avail_data["total_events"] == 0

        # 3. POST /api/agenda/refresh
        res_refresh = client.post("/api/agenda/refresh")
        assert res_refresh.status_code == 200
        refresh_data = json.loads(res_refresh.data)
        assert refresh_data["status"] == "ok"
        assert refresh_data["total_events"] == 3

        # 4. GET /api/agenda/live
        res_live = client.get("/api/agenda/live")
        assert res_live.status_code == 200
        assert isinstance(json.loads(res_live.data), list)

        # 5. GET /agenda.m3u and /api/agenda/playlist.m3u
        res_m3u = client.get("/agenda.m3u")
        assert res_m3u.status_code == 200
        assert res_m3u.mimetype == "audio/x-mpegurl"
        assert b"#EXTM3U" in res_m3u.data

        res_api_m3u = client.get("/api/agenda/playlist.m3u?profile=all")
        assert res_api_m3u.status_code == 200
        assert res_api_m3u.mimetype == "audio/x-mpegurl"
        assert b"#EXTM3U" in res_api_m3u.data

        # 6. POST /api/agenda/probe
        with patch("app.services.agenda_service.agenda_service.probe_candidate_streams") as mock_probe:
            mock_probe.return_value = {
                "status": "ok",
                "live_count": 1,
                "probed": {"s1": {"alive": True, "quality": "1080p", "source_name": "Test"}}
            }
            res_probe = client.post("/api/agenda/probe", json={"streams": [{"stream_id": "s1"}]})
            assert res_probe.status_code == 200
            probe_json = json.loads(res_probe.data)
            assert probe_json["status"] == "ok"
            assert probe_json["live_count"] == 1

            # Invalid payload returns 400
            res_bad = client.post("/api/agenda/probe", json={})
            assert res_bad.status_code == 400
