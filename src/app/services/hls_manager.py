import os
import shutil
import subprocess
import threading
import time
import logging
from app.config import Config

logger = logging.getLogger(__name__)

class HLSManager:
    def __init__(self):
        self.processes = {} # {ace_id: subprocess.Popen}
        self.activity = {}  # {ace_id: timestamp}
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
            internal_host = Config.ACEXY_IP
            if internal_host in ['127.0.0.1', 'localhost', '0.0.0.0']:
                internal_host = 'acexy'
            
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
                
                stream_dir = os.path.join(Config.HLS_DIR, ace_id)
                if os.path.exists(stream_dir):
                    shutil.rmtree(stream_dir)
                    # logger.info(f"Stream stopped. Files kept in {stream_dir} for debugging.")

# Global Instance
hls_manager = HLSManager()
