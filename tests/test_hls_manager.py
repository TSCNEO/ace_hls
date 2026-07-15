import json
import threading
import time
from unittest.mock import Mock, patch

from app.config import Config
from app.services.hls_manager import HLSManager


def bare_manager():
    manager = HLSManager.__new__(HLSManager)
    manager.processes = {}
    manager.activity = {}
    manager.start_times = {}
    manager.validated_sessions = set()
    manager.lock = threading.Lock()
    manager.hw_accel_type = None
    return manager


def running_process():
    process = Mock(returncode=None)
    process.poll.return_value = None
    return process


def test_ffmpeg_uses_unique_upstream_identity(tmp_path):
    manager = bare_manager()
    process = running_process()

    with patch.multiple(Config, HLS_DIR=str(tmp_path), ENABLE_TRANSCODE=False):
        with patch(
            "app.services.settings_manager.settings_manager.get_all",
            return_value={},
        ):
            with patch(
                "app.services.hls_manager.get_acexy_host_for_server",
                return_value="orchestrator",
            ):
                with patch("app.services.hls_manager.subprocess.Popen", return_value=process) as popen:
                    with patch("app.services.hls_manager.threading.Thread") as thread:
                        with patch("app.services.hls_manager.time.sleep"):
                            assert manager.start_stream("a" * 40, "original") == (True, "a" * 40)

    command = popen.call_args.args[0]
    user_agent = command[command.index("-user_agent") + 1]
    assert user_agent.startswith(f"AceHLS-FFmpeg/{'a' * 40}/")
    assert command[command.index("-rw_timeout") + 1] == "60000000"
    assert command[command.index("-i") + 1] == (
        f"http://orchestrator:{Config.ACEXY_PORT}/ace/getstream?id={'a' * 40}"
    )
    assert thread.call_args.kwargs["target"] == manager._analyze_stream
    assert thread.call_args.kwargs["args"] == ("a" * 40,)


def test_force_request_reuses_preparing_session():
    manager = bare_manager()
    stream_id = "b" * 40
    process = running_process()
    manager.processes[stream_id] = process
    manager.activity[stream_id] = time.time()
    manager.start_times[stream_id] = time.time() - 10

    with patch(
        "app.services.settings_manager.settings_manager.get_all",
        return_value={},
    ):
        with patch("app.services.hls_manager.subprocess.Popen") as popen:
            assert manager.start_stream(stream_id, "original", force=True) == (True, stream_id)

    popen.assert_not_called()
    process.terminate.assert_not_called()


def test_ffprobe_reads_local_ts_segment_instead_of_upstream(tmp_path):
    manager = bare_manager()
    stream_id = "c" * 40
    stream_dir = tmp_path / stream_id
    stream_dir.mkdir()
    (stream_dir / "index0.ts").write_bytes(b"media")
    (stream_dir / "index.m3u8").write_text(
        "#EXTM3U\n#EXTINF:4.0,\nindex0.ts\n"
    )
    manager.processes[stream_id] = running_process()
    manager.activity[stream_id] = time.time()
    manager.start_times[stream_id] = time.time()
    probe_result = Mock(
        returncode=0,
        stdout=json.dumps(
            {
                "streams": [
                    {
                        "codec_type": "video",
                        "width": 1920,
                        "height": 1080,
                        "codec_name": "h264",
                        "r_frame_rate": "25/1",
                    },
                    {"codec_type": "audio", "codec_name": "aac"},
                ]
            }
        ),
    )

    with patch.object(Config, "HLS_DIR", str(tmp_path)):
        with patch("app.services.hls_manager.stats_manager.get_stats", return_value=None):
            with patch("app.services.hls_manager.subprocess.run", return_value=probe_result) as run:
                with patch("app.services.hls_manager.stats_manager.update_channel_success") as update:
                    manager._analyze_stream(stream_id)

    command = run.call_args.args[0]
    assert command[-1] == str(stream_dir / "index0.ts")
    assert not command[-1].startswith("http")
    update.assert_called_once_with(
        stream_id,
        {
            "width": 1920,
            "height": 1080,
            "vcodec": "h264",
            "fps": 25,
            "acodec": "aac",
        },
    )


def test_local_fmp4_probe_uses_init_segment(tmp_path):
    manager = bare_manager()
    stream_id = f"{'d' * 40}_max_compat"
    stream_dir = tmp_path / stream_id
    stream_dir.mkdir()
    (stream_dir / "init.mp4").write_bytes(b"init")
    (stream_dir / "index0.m4s").write_bytes(b"media")
    (stream_dir / "index.m3u8").write_text(
        '#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:4.0,\nindex0.m4s\n'
    )

    with patch.object(Config, "HLS_DIR", str(tmp_path)):
        assert manager._local_probe_target(stream_id) == str(stream_dir / "init.mp4")


def test_active_stream_info_exposes_real_request_idle_time(tmp_path):
    manager = bare_manager()
    stream_id = "e" * 40
    stream_dir = tmp_path / stream_id
    stream_dir.mkdir()
    (stream_dir / "index.m3u8").write_text("#EXTM3U\n")
    manager.processes[stream_id] = running_process()
    manager.activity[stream_id] = time.time() - 7
    manager.start_times[stream_id] = time.time() - 20

    with patch.object(Config, "HLS_DIR", str(tmp_path)):
        stream = manager.get_active_streams_info()[0]

    assert stream["process_alive"] is True
    assert 6 <= stream["idle_seconds"] <= 8
    assert stream["manifest_age_seconds"] is not None
