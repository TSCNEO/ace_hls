import os
import shutil
import subprocess
import threading
import time
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
            with self.lock:
                for ace_id, last_active in self.activity.items():
                    idle_time = now - last_active
                    
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
                    if idle_time > 60: # 60 seconds timeout
                        to_remove.append(ace_id)
            
            # Stop them
            for ace_id in to_remove:
                logger.info(f"[Inactivity Monitor] Stopping {ace_id} due to timeout (Idle > 60s).")
                self.stop_stream(ace_id)
                cnt_removed += 1
            
            if cnt_removed > 0:
                logger.info(f"[Inactivity Monitor] Cleaned up {cnt_removed} streams.")

    def update_activity(self, ace_id):
        with self.lock:
            # Check simple ID or Profile-ID (e.g., id_720p)
            if ace_id in self.processes:
                self.activity[ace_id] = time.time()

    def start_stream(self, ace_id, profile=None, overrides=None):
        """
        Starts the HLS stream. 
        profile: None (Original), '720p', '480p'
        overrides: Dict (Deprecated, backward compat). Now uses SettingsManager.
        """
        from app.services.settings_manager import settings_manager
        settings = settings_manager.get_all()

        # Determine params (Settings > Config Defaults)
        bitrate_720p = settings.get('transcode_720p_bitrate', Config.TRANSCODE_720P_BITRATE)
        bitrate_480p = settings.get('transcode_480p_bitrate', Config.TRANSCODE_480P_BITRATE)
        crf_compat = settings.get('transcode_compat_crf', Config.TRANSCODE_COMPAT_CRF)

        # If profile is original (or None), do NOT append suffix.

        with self.lock:
            # Check if active - Simplified: If overrides are present, force restart to apply them?
            # Or assume frontend handles stop/start? 
            # For now, let's assume if it's running we return it. If user wants to apply new settings, they must Stop first.
            if effective_id in self.processes:
                proc = self.processes[effective_id]
                if proc.poll() is None:
                    self.activity[effective_id] = time.time()
                    return True, effective_id # Return effective ID for URL gen
                else:
                    del self.processes[effective_id]
            
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

            # --- BUILD COMMAND ---
            cmd = ["ffmpeg", "-fflags", "+genpts+igndts", "-i", start_url]
            
            # Transcoding Logic
            if not Config.ENABLE_TRANSCODE or not profile or profile == 'original':
                # Original / Passthrough (Simpler is better for stability)
                cmd.extend(["-c", "copy"])
            else:
                # Transcoding: Strict mapping
                cmd.extend(["-map", "0:v", "-map", "0:a", "-sn", "-dn", "-ignore_unknown"])

                if self.hw_accel_type == 'vaapi':
                    # VAAPI Init
                    cmd.insert(1, "-hwaccel")
                    cmd.insert(2, "vaapi")
                    cmd.insert(3, "-hwaccel_device")
                    cmd.insert(4, "/dev/dri/renderD128")
                    cmd.insert(5, "-hwaccel_output_format")
                    cmd.insert(6, "vaapi")
                    
                    if profile == '720p':
                        cmd.extend(["-vf", "scale_vaapi=w=-2:h=720:format=nv12", "-c:v", "h264_vaapi", "-b:v", bitrate_720p])
                    elif profile == '480p':
                        cmd.extend(["-vf", "scale_vaapi=w=-2:h=480:format=nv12", "-c:v", "h264_vaapi", "-b:v", bitrate_480p])
                    elif profile == 'max_compat':
                        # Max Compatibility: Same Resolution but Force Re-encode to H.264
                        # Just format conversion to NV12 for VAAPI is enough to trigger encode
                        cmd.extend(["-vf", "scale_vaapi=format=nv12", "-c:v", "h264_vaapi", "-b:v", "5000k", "-g", "50"])
                    
                    cmd.extend(["-c:a", "aac", "-b:a", "128k"]) # Encode audio too just in case
                else:
                    # CPU Fallback
                    logger.warning(f"No HW Accel detected. CPU transcoding for {profile}!")
                    if profile == '720p':
                        cmd.extend(["-vf", "scale=-2:720", "-c:v", "libx264", "-preset", "veryfast", "-b:v", bitrate_720p])
                    elif profile == '480p':
                        cmd.extend(["-vf", "scale=-2:480", "-c:v", "libx264", "-preset", "veryfast", "-b:v", bitrate_480p])
                    elif profile == 'max_compat':
                        # CPU: Re-encode with libx264, no scale
                        cmd.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", crf_compat, "-g", "50"])
                    
                    cmd.extend(["-c:a", "aac", "-b:a", "128k"])

            # Global HLS Flags
            cmd.extend([
                "-hls_time", "4",
                "-hls_list_size", "6",
                "-hls_flags", "delete_segments",
                output_file
            ])
            
            logger.info(f"Starting FFMPEG for {effective_id} [Profile: {profile}]: {' '.join(cmd)}")
            
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
            
            self.processes[effective_id] = proc
            self.activity[effective_id] = time.time()
            self.start_times[effective_id] = time.time()
            if effective_id in self.validated_sessions:
                self.validated_sessions.remove(effective_id)

            # Force probe if Original profile to ensure fresh data and valid cache for variants
            force_probe = (profile == 'original')
            threading.Thread(target=self._analyze_stream, args=(effective_id, start_url, force_probe), daemon=True).start()

            # Check dead-on-arrival
            time.sleep(1)
            if proc.poll() is not None:
                logger.error(f"FFMPEG failed for {effective_id}. Check {log_file}")
                return False, effective_id

            return True, effective_id

    def stop_stream(self, ace_id):
        with self.lock:
            if ace_id in self.activity:
                 del self.activity[ace_id]

            if ace_id in self.processes:
                proc = self.processes[ace_id]
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                del self.processes[ace_id]
                if ace_id in self.start_times: del self.start_times[ace_id]
                if ace_id in self.validated_sessions: self.validated_sessions.remove(ace_id)
                
                stream_dir = os.path.join(Config.HLS_DIR, ace_id)
        if os.path.exists(stream_dir):
                    shutil.rmtree(stream_dir)

    def _analyze_stream(self, ace_id, stream_url, force_probe=False):
        """Runs ffprobe on the INPUT stream to capture original quality."""
        
        # Check cache first to avoid redundant probes/timeouts
        # ONLY if force_probe is False (i.e. transcoding variants)
        cached = None
        if not force_probe:
            # 1. Check exact ID
            cached = stats_manager.get_stats(ace_id)
            if not cached or not cached.get('tech_info'):
                # 2. Check base ID (if variant)
                if len(ace_id) > 40:
                    base_id = ace_id[:40] 
                    cached = stats_manager.get_stats(base_id)
        
        if cached and cached.get('tech_info'):
            logger.info(f"Skipping probe for {ace_id}, using cached tech info.")
            # Ensure the current ID has the stats too (if we found it on base_id)
            if ace_id != cached.get('id', ''): # effectively just update
                 stats_manager.update_channel_success(ace_id, cached['tech_info'])
            
            with self.lock:
                self.validated_sessions.add(ace_id)
            return

        time.sleep(15) # Wait for stream to stabilize/buffer
        
        with self.lock:
            # Check if still running
            if ace_id not in self.processes:
                return

        logger.info(f"Analyzing stream {ace_id}...")
        try:
            cmd = [
                "ffprobe", 
                "-v", "quiet", 
                "-print_format", "json", 
                "-show_streams", 
                "-show_format",
                stream_url
            ]
            # Timeout is important to avoid hanging threads
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if result.returncode == 0:
                import json
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
                    logger.info(f"Analysis for {ace_id}: {tech_info}")
                    # Update stats with technical info
                    stats_manager.update_channel_success(ace_id, tech_info)
                    
                    # Also mark as validated since it responded to ffprobe
                    with self.lock:
                         self.validated_sessions.add(ace_id)
            else:
                logger.warning(f"ffprobe failed for {ace_id}")

        except Exception as e:
            logger.error(f"Analysis error for {ace_id}: {e}")

# Global Instance
hls_manager = HLSManager()
