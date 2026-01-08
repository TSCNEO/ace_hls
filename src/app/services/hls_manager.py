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
                    if now - last_active > 60: # 60 seconds timeout
                        to_remove.append(ace_id)
            
            # Stop them
            for ace_id in to_remove:
                logger.info(f"[Inactivity Monitor] Stopping {ace_id} due to timeout.")
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
            os.makedirs(stream_dir)

            # --- UNIFIED CONNECTION LOGIC ---
            internal_host = Config.ACEXY_IP
            if internal_host in ['127.0.0.1', 'localhost', '0.0.0.0']:
                internal_host = 'acexy'
            
            start_url = f"http://{internal_host}:{Config.ACEXY_PORT}/ace/getstream?id={ace_id}"
            logger.info(f"Connecting to AceXY (Internal): {internal_host}:{Config.ACEXY_PORT}")

            output_file = os.path.join(stream_dir, "index.m3u8")
            cmd = [
                "ffmpeg",
                "-i", start_url,
                "-c", "copy",
                "-hls_time", "6",
                "-hls_list_size", "5",
                "-hls_flags", "delete_segments",
                output_file
            ]
            
            logger.info(f"Starting FFMPEG for {ace_id}: {' '.join(cmd)}")
            # Log to file for debugging
            log_file = os.path.join(stream_dir, "ffmpeg.log")
            with open(log_file, "w") as log:
                 proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
            
            self.processes[ace_id] = proc
            self.activity[ace_id] = time.time()
            
            # Check if it died immediately
            time.sleep(1)
            if proc.poll() is not None:
                logger.error(f"FFMPEG failed for {ace_id}. Check {log_file}")
                # Try to read the log to show it
                try:
                    with open(log_file, "r") as f:
                        logger.error(f"FFMPEG Output: {f.read()}")
                except:
                    pass
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

# Global Instance
hls_manager = HLSManager()
