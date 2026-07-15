import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
import logging
from app.utils import get_acexy_host_for_server
from app.config import Config

logger = logging.getLogger(__name__)

# Lazy import to avoid potential circular issues, though StatsManager seems safe.
from app.services.stats_manager import stats_manager

class HLSManager:
    def __init__(self):
        self.processes = {} # {ace_id: subprocess.Popen}
        self.activity = {}  # {ace_id: timestamp_of_last_request}
        self.start_times = {} # {ace_id: timestamp_of_start} for validation
        self.validated_sessions = set() # {ace_id} to ensure we count success only once per run
        self.lock = threading.Lock()
        
        # HW Acceleration Detection
        self.hw_accel_type = self._detect_hw_accel()
        if Config.ENABLE_TRANSCODE:
            logger.info(f"Transcoding Enabled. HW Accel: {self.hw_accel_type if self.hw_accel_type else 'None (CPU)'}")
        else:
            logger.info("Transcoding Disabled.")
        
        # Cleanup on startup
        if os.path.exists(Config.HLS_DIR):
            logger.info(f"Cleaning HLS directory: {Config.HLS_DIR}")
            shutil.rmtree(Config.HLS_DIR)
            
        if not os.path.exists(Config.HLS_DIR):
            os.makedirs(Config.HLS_DIR)
        
        # Start background monitor
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

    def _detect_hw_accel(self):
        """Detects available HW acceleration (VAAPI/QSV)."""
        # Simple check for /dev/dri
        if os.path.exists('/dev/dri/renderD128'):
            # Ideally we'd probe ffmpeg, but assumption for now:
            # If device exists, we try VAAPI as it's most generic for Intel/AMD on Linux
            return 'vaapi'
        return None

    def _monitor_loop(self):
        """Checks for inactive streams every 10 seconds."""
        while True:
            time.sleep(10)
            now = time.time()
            cnt_removed = 0
            
            # Identify inactive streams first (to avoid blocking excessively)
            to_remove = []
            dead_streams = []
            with self.lock:
                for ace_id, last_active in self.activity.items():
                    idle_time = now - last_active
                    proc = self.processes.get(ace_id)
                    if proc and proc.poll() is not None:
                        dead_streams.append((ace_id, proc.returncode))
                        continue
                    
                    # --- PASSIVE VALIDATION ---
                    # If stream has been running > 30s and active, mark as success
                    if ace_id in self.start_times:
                        run_duration = now - self.start_times[ace_id]
                        if run_duration > 30 and ace_id not in self.validated_sessions:
                            # Verify process is actually alive
                            proc = self.processes.get(ace_id)
                            if proc and proc.poll() is None:
                                logger.info(f"[Monitor] Validating {ace_id} (Running {run_duration:.0f}s)")
                                stats_manager.update_channel_success(ace_id)
                                self.validated_sessions.add(ace_id)

                    # logger.info(f"[Monitor] {ace_id} idle for {idle_time:.1f}s") # Verbose debug
                    if idle_time > Config.HLS_IDLE_TIMEOUT:
                        to_remove.append(ace_id)
            
            # Stop them
            for ace_id, return_code in dead_streams:
                logger.error(
                    "FFmpeg exited unexpectedly for %s (exit_code=%s). Preserving logs.",
                    ace_id,
                    return_code,
                )
                with self.lock:
                    self._cleanup_stream_locked(ace_id, remove_files=False)

            for ace_id in to_remove:
                idle_seconds = int(now - self.activity.get(ace_id, now))
                logger.info(
                    "[Inactivity Monitor] Stopping %s: no HLS requests for %ss "
                    "(limit=%ss).",
                    ace_id,
                    idle_seconds,
                    Config.HLS_IDLE_TIMEOUT,
                )
                self.stop_stream(ace_id, reason="inactivity")
                cnt_removed += 1
            
            if cnt_removed > 0:
                logger.info(f"[Inactivity Monitor] Cleaned up {cnt_removed} streams.")

    def update_activity(self, ace_id):
        with self.lock:
            # Check simple ID or Profile-ID (e.g., id_720p)
            if ace_id in self.processes:
                self.activity[ace_id] = time.time()

    def _cleanup_stream_locked(self, stream_id, remove_files=True):
        if stream_id in self.activity:
            del self.activity[stream_id]

        if stream_id in self.processes:
            proc = self.processes[stream_id]
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
            del self.processes[stream_id]

        if stream_id in self.start_times:
            del self.start_times[stream_id]
        if stream_id in self.validated_sessions:
            self.validated_sessions.remove(stream_id)

        if remove_files:
            stream_dir = os.path.join(Config.HLS_DIR, stream_id)
            if os.path.exists(stream_dir):
                shutil.rmtree(stream_dir)

    def start_stream(self, ace_id, profile=None, overrides=None, force=False):
        """
        Starts the HLS stream. 
        profile: None (Original), '720p', '480p'
        overrides: Dict (Deprecated, backward compat). Now uses SettingsManager.
        force: Restart an existing stale stream; healthy/preparing sessions are reused.
        """
        from app.services.settings_manager import settings_manager
        settings = settings_manager.get_all()

        # Determine params (Settings > Config Defaults)
        # Determine params (Settings > Config Defaults)
        bitrate_720p = settings.get('transcode_720p_bitrate', Config.TRANSCODE_720P_BITRATE)
        bitrate_480p = settings.get('transcode_480p_bitrate', Config.TRANSCODE_480P_BITRATE)
        crf_compat = settings.get('transcode_compat_crf', Config.TRANSCODE_COMPAT_CRF)
        
        # v1.8.2 Advanced Settings
        video_codec = settings.get('transcode_video_codec', 'h264') # h264, hevc
        audio_bitrate = settings.get('transcode_audio_bitrate', '128k')
        preset = settings.get('transcode_preset', 'veryfast')
        deinterlace = settings.get('transcode_deinterlace', False)

        # If profile is original (or None), do NOT append suffix.
        effective_id = f"{ace_id}_{profile}" if profile and profile != 'original' else ace_id

        with self.lock:
            if force and effective_id in self.processes:
                proc = self.processes[effective_id]
                if proc.poll() is None and self._session_is_reusable(effective_id):
                    logger.info("Reusing healthy stream %s despite force request.", effective_id)
                    self.activity[effective_id] = time.time()
                    return True, effective_id
                logger.info("Force restarting stale stream %s.", effective_id)
                self._cleanup_stream_locked(effective_id)

            # Check if active
            if effective_id in self.processes:
                proc = self.processes[effective_id]
                if proc.poll() is None:
                    self.activity[effective_id] = time.time()
                    return True, effective_id 
                else:
                    self._cleanup_stream_locked(effective_id)
            
            # Prepare directory
            stream_dir = os.path.join(Config.HLS_DIR, effective_id)
            if os.path.exists(stream_dir):
                shutil.rmtree(stream_dir)
            
            if not os.path.exists(Config.HLS_DIR):
                os.makedirs(Config.HLS_DIR)
            os.makedirs(stream_dir)

            # --- UNIFIED CONNECTION LOGIC ---
            internal_host = get_acexy_host_for_server()
            start_url = f"http://{internal_host}:{Config.ACEXY_PORT}/ace/getstream?id={ace_id}"
            
            log_file = os.path.join(stream_dir, "ffmpeg.log")
            env = os.environ.copy()
            env["FFREPORT"] = f"file={log_file}:level=32"
            output_file = os.path.join(stream_dir, "index.m3u8")
            client_id = uuid.uuid4().hex
            user_agent = f"AceHLS-FFmpeg/{effective_id}/{client_id}"

            # --- BUILD COMMAND ---
            # Added resilience flags for slow streams (v2.2.2)
            cmd = ["ffmpeg", 
                   "-analyzeduration", "10000000", "-probesize", "10000000", # 10s buffer for analysis
                   "-rw_timeout", str(Config.FFMPEG_RW_TIMEOUT * 1_000_000),
                   "-user_agent", user_agent,
                   "-fflags", "+genpts+igndts", "-i", start_url]
            
            # Transcoding Logic
            is_recode_profile = Config.ENABLE_TRANSCODE and profile and profile != 'original'

            if not Config.ENABLE_TRANSCODE or not profile or profile == 'original':
                # True original passthrough. The web UI normally uses the upstream proxy for this.
                cmd.extend(["-c", "copy"])
            else:
                # Transcoding: Strict mapping
                cmd.extend(["-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn", "-ignore_unknown"])

                if self.hw_accel_type == 'vaapi':
                    # VAAPI Init
                    cmd.insert(1, "-hwaccel")
                    cmd.insert(2, "vaapi")
                    cmd.insert(3, "-hwaccel_device")
                    cmd.insert(4, "/dev/dri/renderD128")
                    cmd.insert(5, "-hwaccel_output_format")
                    cmd.insert(6, "vaapi")
                    
                    # Codec Selection (VAAPI)
                    vcodec = "h264_vaapi" if video_codec == 'h264' else "hevc_vaapi"
                    
                    # Filters Construction
                    filters = []
                    if deinterlace:
                        filters.append("deinterlace_vaapi")
                    
                    if profile == '720p':
                        filters.append("scale_vaapi=w=-2:h=720:format=nv12")
                        cmd.extend(["-c:v", vcodec, "-b:v", bitrate_720p])
                    elif profile == '480p':
                        filters.append("scale_vaapi=w=-2:h=480:format=nv12")
                        cmd.extend(["-c:v", vcodec, "-b:v", bitrate_480p])
                    elif profile == 'max_compat':
                        # Max Compatibility: Same Resolution but Force Re-encode to H.264
                        # Use ACP/QP instead of fixed bitrate to respect CRF setting.
                        # VAAPI uses -qp for Constant Quantization Parameter (similar to CRF)
                        filters.append("scale_vaapi=format=nv12")
                        cmd.extend(["-c:v", "h264_vaapi", "-qp", str(crf_compat), "-g", "50", "-bf", "0"])
                    
                    if filters:
                        cmd.extend(["-vf", ",".join(filters)])
                    
                else:
                    # CPU Fallback
                    logger.warning(f"No HW Accel detected. CPU transcoding for {profile}!")
                    
                    # Codec Selection (CPU)
                    vcodec = "libx264" if video_codec == 'h264' else "libx265"
                    
                    # Filters Construction
                    filters = []
                    if deinterlace:
                        filters.append("yadif")
                        
                    if profile == '720p':
                        filters.append("scale=-2:720")
                        cmd.extend(["-c:v", "libx264", "-preset", preset, "-b:v", bitrate_720p])
                    elif profile == '480p':
                        filters.append("scale=-2:480")
                        cmd.extend(["-c:v", "libx264", "-preset", preset, "-b:v", bitrate_480p])
                    elif profile == 'max_compat':
                        cmd.extend(["-c:v", "libx264", "-preset", preset, "-crf", crf_compat, "-g", "50"])
                    
                    if filters:
                        cmd.extend(["-vf", ",".join(filters)])
                
                # Audio Encoding (Common)
                cmd.extend([
                    "-pix_fmt", "yuv420p",
                    "-profile:v", "main",
                    "-level", "4.1",
                    "-sc_threshold", "0",
                    "-keyint_min", "50",
                    "-c:a", "aac",
                    "-ac", "2",
                    "-ar", "48000",
                    "-b:a", audio_bitrate
                ])

            # Global HLS Flags
            hls_flags = "delete_segments+independent_segments" if is_recode_profile else "delete_segments"
            cmd.extend(["-hls_time", "4", "-hls_list_size", "6", "-hls_flags", hls_flags])

            if is_recode_profile:
                cmd.extend([
                    "-hls_segment_type", "fmp4",
                    "-hls_fmp4_init_filename", "init.mp4",
                    "-hls_segment_filename", os.path.join(stream_dir, "index%d.m4s")
                ])

            cmd.append(output_file)
            
            logger.info(f"Starting FFMPEG for {effective_id} [Profile: {profile}]: {' '.join(cmd)}")
            
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
            
            self.processes[effective_id] = proc
            self.activity[effective_id] = time.time()
            self.start_times[effective_id] = time.time()
            if effective_id in self.validated_sessions:
                self.validated_sessions.remove(effective_id)

            threading.Thread(
                target=self._analyze_stream,
                args=(effective_id,),
                daemon=True,
            ).start()

            # Check dead-on-arrival
            time.sleep(1)
            if proc.poll() is not None:
                logger.error(f"FFMPEG failed for {effective_id}. Check {log_file}")
                self._cleanup_stream_locked(effective_id, remove_files=False)
                return False, effective_id

            return True, effective_id

    def _session_is_reusable(self, stream_id):
        """Reuse young sessions and streams whose manifest is still advancing."""
        started_at = self.start_times.get(stream_id, 0)
        if started_at and (time.time() - started_at) < 60:
            return True

        manifest = os.path.join(Config.HLS_DIR, stream_id, 'index.m3u8')
        try:
            return (time.time() - os.path.getmtime(manifest)) < 15
        except OSError:
            return False

    def stop_stream(self, ace_id, reason="manual"):
        with self.lock:
            if ace_id in self.processes:
                logger.info("Stopping stream %s (reason=%s).", ace_id, reason)
            self._cleanup_stream_locked(ace_id)

    def get_active_streams_info(self):
        """Returns list of active streams with metadata for dashboard."""
        streams = []
        with self.lock:
            for pid, proc in self.processes.items():
                start_time = self.start_times.get(pid, 0)
                uptime = int(time.time() - start_time) if start_time else 0
                last_access = self.activity.get(pid, 0)
                manifest = os.path.join(Config.HLS_DIR, pid, 'index.m3u8')
                try:
                    manifest_age = round(time.time() - os.path.getmtime(manifest), 1)
                except OSError:
                    manifest_age = None
                
                # Try to get CPU usage of ffmpeg process? (Maybe too heavy here)
                # Just basic info
                streams.append({
                    "id": pid,
                    "uptime": uptime,
                    "profile": pid.split('_')[-1] if '_' in pid else "original",
                    "process_alive": proc.poll() is None,
                    "idle_seconds": round(time.time() - last_access, 1) if last_access else None,
                    "manifest_age_seconds": manifest_age,
                })
        return streams

    def _analyze_stream(self, playback_id):
        """Probe generated HLS files without opening a second upstream client."""
        
        # Identify Raw ID (Source) from Playback ID (Process key)
        # Acestream IDs are 40 chars. playback_id might have suffixes.
        raw_id = playback_id[:40]

        # Check cache first to avoid redundant probes/timeouts
        # Cache expires after 24h (86400s) to refresh technical info
        now = time.time()
        stats = stats_manager.get_stats(raw_id)
        cached = None
        if stats and stats.get('tech_info'):
            last_ok = stats.get('last_ok', 0)
            if (now - last_ok) < 86400: # 24h validity
                cached = stats
        
        if cached:
            logger.info(f"Skipping probe for {raw_id} (playing {playback_id}), using cached tech info (Age: {int(now - cached.get('last_ok',0))}s).")
            # Mark raw_id as active/valid
            stats_manager.update_channel_success(raw_id, cached['tech_info'])
            
            with self.lock:
                self.validated_sessions.add(playback_id)
            return

        probe_target = self._wait_for_local_probe_target(playback_id, timeout=30)
        if not probe_target:
            logger.warning("No local media available for ffprobe: %s", playback_id)
            return

        logger.info("Analyzing local HLS output for %s via %s", raw_id, probe_target)
        try:
            cmd = [
                "ffprobe", 
                "-v", "quiet", 
                "-print_format", "json", 
                "-show_streams", 
                "-show_format",
                probe_target,
            ]
            # Timeout is important to avoid hanging threads
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                
                tech_info = {}
                for stream in data.get('streams', []):
                    if stream['codec_type'] == 'video':
                        tech_info['width'] = stream.get('width')
                        tech_info['height'] = stream.get('height')
                        tech_info['vcodec'] = stream.get('codec_name')
                        # FPS calculation can be tricky ("50/1" or "50")
                        fps_str = stream.get('r_frame_rate')
                        if fps_str:
                            try:
                                num, den = map(int, fps_str.split('/'))
                                if den > 0:
                                    tech_info['fps'] = round(num / den)
                            except:
                                pass
                                
                    elif stream['codec_type'] == 'audio':
                        tech_info['acodec'] = stream.get('codec_name')
                
                if tech_info:
                    logger.info(f"Analysis success for {raw_id}: {tech_info}")
                    # Update stats for the RAW SOURCE ID so all profiles share it
                    stats_manager.update_channel_success(raw_id, tech_info)
                    
                    # Also mark as validated since it responded to ffprobe
                    with self.lock:
                        self.validated_sessions.add(playback_id)
            else:
                logger.warning("ffprobe failed for %s (exit_code=%s)", raw_id, result.returncode)
        except Exception as e:
            logger.error(f"Error analyzing stream {raw_id}: {e}")

    def _wait_for_local_probe_target(self, playback_id, timeout=30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                proc = self.processes.get(playback_id)
                if not proc or proc.poll() is not None:
                    return None

            target = self._local_probe_target(playback_id)
            if target:
                return target
            time.sleep(0.5)
        return None

    def _local_probe_target(self, playback_id):
        stream_dir = os.path.join(Config.HLS_DIR, playback_id)
        manifest = os.path.join(stream_dir, 'index.m3u8')
        try:
            with open(manifest, 'r') as handle:
                lines = [line.strip() for line in handle]
        except OSError:
            return None

        init_candidates = []
        media_candidates = []
        for line in lines:
            if line.startswith('#EXT-X-MAP:'):
                match = re.search(r'URI="([^"]+)"', line)
                if match:
                    init_candidates.append(match.group(1))
            elif line and not line.startswith('#'):
                media_candidates.append(line)

        for relative in init_candidates + list(reversed(media_candidates)):
            relative = relative.split('?', 1)[0]
            candidate = os.path.abspath(os.path.join(stream_dir, relative))
            if os.path.commonpath([stream_dir, candidate]) != os.path.abspath(stream_dir):
                continue
            try:
                if os.path.getsize(candidate) > 0:
                    return candidate
            except OSError:
                continue
        return None

# Global Instance
hls_manager = HLSManager()
