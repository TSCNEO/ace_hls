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
        
        # Cleanup on startup
        if os.path.exists(Config.HLS_DIR):
            logger.info(f"Cleaning HLS directory: {Config.HLS_DIR}")
            shutil.rmtree(Config.HLS_DIR)
            
        if not os.path.exists(Config.HLS_DIR):
            os.makedirs(Config.HLS_DIR)
        
        # Start background monitor
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

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
            # Only update if we know about this stream (it's running)
            if ace_id in self.processes:
                self.activity[ace_id] = time.time()

    def start_stream(self, ace_id):
        with self.lock:
            # Check if active
            if ace_id in self.processes:
                proc = self.processes[ace_id]
                if proc.poll() is None:
                    self.activity[ace_id] = time.time() # Refresh
                    return True # Already running
                else:
                    del self.processes[ace_id]

            # Prepare directory
            stream_dir = os.path.join(Config.HLS_DIR, ace_id)
            if os.path.exists(stream_dir):
                shutil.rmtree(stream_dir)
            
            # Ensure parent exits
            if not os.path.exists(Config.HLS_DIR):
                os.makedirs(Config.HLS_DIR)
                
            os.makedirs(stream_dir)

            # --- UNIFIED CONNECTION LOGIC ---
            internal_host = get_acexy_host_for_server()
            
            start_url = f"http://{internal_host}:{Config.ACEXY_PORT}/ace/getstream?id={ace_id}"
            logger.info(f"Connecting to AceXY (Internal): {internal_host}:{Config.ACEXY_PORT}")

            log_file = os.path.join(stream_dir, "ffmpeg.log")
            env = os.environ.copy()
            env["FFREPORT"] = f"file={log_file}:level=32" # 32=INFO, 48=DEBUG

            # Define output_file BEFORE using it in cmd
            output_file = os.path.join(stream_dir, "index.m3u8")

            # Added -fflags +genpts+igndts to tolerate bad timestamps
            # Kept -bsf:v h264_mp4toannexb as it's required for TS
            cmd = [
                "ffmpeg",
                "-fflags", "+genpts+igndts", 
                "-i", start_url,
                "-map", "0:v", "-map", "0:a", # Only map video and audio
                "-sn", "-dn", # Drop subtitles and data
                "-ignore_unknown",
                "-c", "copy",
                "-bsf:v", "h264_mp4toannexb", 
                "-hls_time", "4", # Slightly smaller segments
                "-hls_list_size", "6",
                "-hls_flags", "delete_segments",
                output_file
            ]
            
            logger.info(f"Starting FFMPEG for {ace_id}: {' '.join(cmd)}")
            
            # Use shell=False, but pass env. No stdout redirection needed for log (FFREPORT handles it)
            # We redirect stdout/stderr to DEVNULL to keep container logs clean, 
            # unless we want to debug startup issues.
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
            
            self.processes[ace_id] = proc
            self.activity[ace_id] = time.time()
            self.start_times[ace_id] = time.time()
            if ace_id in self.validated_sessions:
                self.validated_sessions.remove(ace_id)

            # Start Metadata Analysis (Async)
            threading.Thread(target=self._analyze_stream, args=(ace_id, start_url), daemon=True).start()

            # Check if it died immediately
            time.sleep(1)
            if proc.poll() is not None:
                logger.error(f"FFMPEG failed for {ace_id}. Check {log_file}")
                return False

            return True

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
                    # logger.info(f"Stream stopped. Files kept in {stream_dir} for debugging.")

    def _analyze_stream(self, ace_id, stream_url):
        """Runs ffprobe to extract resolution, fps, codecs"""
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
