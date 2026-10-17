import json
import os
import signal
import subprocess
import threading
import time
from unittest.mock import Mock, call, patch

import pytest

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


def stubborn_process():
    """Alive process whose wait() times out after terminate() and works after kill()."""
    process = running_process()
    process.wait.side_effect = [
        subprocess.TimeoutExpired(cmd="ffmpeg", timeout=2),
        0,
    ]
    return process


def spawn_sigterm_ignoring_child():
    """Real child process that ignores SIGTERM so only SIGKILL can stop it.

    The child announces readiness on stdout so the caller never signals it
    before the SIGTERM handler is actually installed.
    """
    proc = subprocess.Popen(
        [
            "python3",
            "-c",
            (
                "import signal, sys, time\n"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                "sys.stdout.write('ready\\n')\n"
                "sys.stdout.flush()\n"
                "time.sleep(120)\n"
            ),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    assert proc.stdout.readline().strip() == "ready"
    return proc


def running_child():
    """Real child process that exits normally on SIGTERM."""
    return subprocess.Popen(
        ["python3", "-c", "import time; time.sleep(120)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_ffmpeg_uses_unique_upstream_identity(tmp_path):
    manager = bare_manager()
    process = running_process()

    with patch.multiple(Config, HLS_DIR=str(tmp_path), ENABLE_TRANSCODE=False):
        with patch(
            "app.services.settings_manager.settings_manager.get_all",
            return_value={},
        ):
            with patch(
                "app.services.hls_manager.get_stream_proxy_host_for_server",
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
        f"http://orchestrator:{Config.STREAM_PROXY_PORT}/ace/getstream?id={'a' * 40}"
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


def test_analyze_stream_validates_session_without_server_ffprobe(tmp_path):
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

    cached_stats = {
        "tech_info": {
            "width": 1920,
            "height": 1080,
            "vcodec": "h264",
            "fps": 50,
            "acodec": "aac",
        }
    }

    with patch.object(Config, "HLS_DIR", str(tmp_path)):
        with patch("app.services.hls_manager.stats_manager.get_stats", return_value=cached_stats):
            with patch("app.services.hls_manager.subprocess.run") as run:
                with patch("app.services.hls_manager.stats_manager.update_channel_success") as update:
                    manager._analyze_stream(stream_id)

    run.assert_not_called()
    assert stream_id in manager.validated_sessions
    update.assert_called_once_with(stream_id, cached_stats["tech_info"])


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


def test_cleanup_harvests_process_after_force_kill(tmp_path):
    """A process that ignores SIGTERM must be killed AND reaped, never left defunct."""
    manager = bare_manager()
    stream_id = "f" * 40
    process = stubborn_process()
    manager.processes[stream_id] = process
    manager.activity[stream_id] = time.time()

    with patch.object(Config, "HLS_DIR", str(tmp_path)):
        manager._cleanup_stream_locked(stream_id)

    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    # First wait() timed out; a second wait() is mandatory to harvest the zombie.
    assert process.wait.call_count == 2
    assert process.wait.call_args_list[1] == call(timeout=2)
    assert stream_id not in manager.processes


def test_reap_process_returns_true_after_sigkill(tmp_path):
    """_reap_process must force-kill and harvest a SIGTERM-ignoring child."""
    manager = bare_manager()
    proc = spawn_sigterm_ignoring_child()
    try:
        assert proc.poll() is None
        assert manager._reap_process(proc, timeout=1.0) is True
        assert proc.returncode == -signal.SIGKILL
        # A reaped child can no longer be waited for -> no defunct entry left behind.
        with pytest.raises(ChildProcessError):
            os.waitpid(proc.pid, os.WNOHANG)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_reap_process_terminates_cooperative_child_without_kill():
    """Cooperative children must exit via SIGTERM; kill() is a last resort."""
    manager = bare_manager()
    proc = running_child()
    try:
        assert manager._reap_process(proc, timeout=5.0) is True
        assert proc.returncode == -signal.SIGTERM
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_reap_process_skips_already_dead_process():
    """Already-exited processes are harvested without signals."""
    manager = bare_manager()
    process = Mock(returncode=0)
    process.poll.return_value = 0

    assert manager._reap_process(process) is True
    process.terminate.assert_not_called()
    process.kill.assert_not_called()
    process.wait.assert_called_once()


def test_stop_stream_reaps_force_killed_process(tmp_path):
    """stop_stream must leave no zombie behind for a SIGTERM-ignoring stream."""
    manager = bare_manager()
    stream_id = "g" * 40
    process = stubborn_process()
    manager.processes[stream_id] = process
    manager.activity[stream_id] = time.time()

    with patch.object(Config, "HLS_DIR", str(tmp_path)):
        manager.stop_stream(stream_id, reason="test")

    process.kill.assert_called_once()
    assert process.wait.call_count == 2
    assert stream_id not in manager.processes


def test_cleanup_leaves_no_defunct_child_in_process_table(tmp_path):
    """End-to-end: a real SIGTERM-ignoring child must not survive as a zombie."""
    manager = bare_manager()
    stream_id = "h" * 40
    proc = spawn_sigterm_ignoring_child()
    manager.processes[stream_id] = proc
    manager.activity[stream_id] = time.time()
    manager.start_times[stream_id] = time.time()

    try:
        with patch.object(Config, "HLS_DIR", str(tmp_path)):
            manager._cleanup_stream_locked(stream_id)

        assert stream_id not in manager.processes

        # Inspect /proc straight away: Popen.poll() would itself reap the child
        # and hide a leaked zombie, so it must not run before this check.
        state = read_process_state(proc.pid)
        assert state is None, (
            f"child {proc.pid} still present in the process table "
            f"with state {state!r} after cleanup"
        )

        # A fully reaped child can no longer be waited on.
        with pytest.raises(ChildProcessError):
            os.waitpid(proc.pid, os.WNOHANG)
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def read_process_state(pid):
    """Return the single-letter state from /proc/<pid>/stat, or None if gone."""
    try:
        with open(f"/proc/{pid}/stat", "r") as handle:
            fields = handle.read().rsplit(")", 1)[1].split()
    except OSError:
        return None
    return fields[0] if fields else None
