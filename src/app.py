import os
import time
import json

import re
import logging
import requests
import subprocess
import shutil
import threading
from flask import Flask, jsonify, send_from_directory, Response, request

# Configuration
URL_ORIGEN = os.environ.get("URL_ORIGEN", "https://ipfs.io/ipns/k2k4r8oqlcjxsritt5mczkcn4mmvcmymbqw7113fz2flkrerfwfps004/data/listas/lista_iptv.m3u")

# External Config (For M3U and Remote Connection)
ACEXY_IP = os.environ.get("ACEXY_IP", "127.0.0.1")
ACEXY_PORT = os.environ.get("ACEXY_PORT", "8080")

CACHE_DURATION = int(os.environ.get("CACHE_DURATION", 300))
DATA_DIR = os.environ.get("DATA_DIR", "./data")

# File paths

JSON_FILE = os.path.join(DATA_DIR, "channels.json")
M3U_FILE = os.path.join(DATA_DIR, "ace_hls.m3u")
HLS_DIR = os.path.join(DATA_DIR, "hls")

# Logger setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__, static_url_path='')

class HLSManager:
    def __init__(self):
        self.processes = {} # {ace_id: subprocess.Popen}
        self.activity = {}  # {ace_id: timestamp}
        self.lock = threading.Lock()
        if not os.path.exists(HLS_DIR):
            os.makedirs(HLS_DIR)
        
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
            stream_dir = os.path.join(HLS_DIR, ace_id)
            if os.path.exists(stream_dir):
                shutil.rmtree(stream_dir)
            os.makedirs(stream_dir)

            # --- UNIFIED CONNECTION LOGIC ---
            # As requested: IP_SERVIDOR and PUERTO determine both internal and external connection.
            # 1. Internal (ffmpeg): Connects to IP_SERVIDOR:PUERTO.
            #    Adjustment: If IP is '127.0.0.1' or 'localhost', we must use 'acexy' to work inside Docker.
            
            internal_host = ACEXY_IP
            if internal_host in ['127.0.0.1', 'localhost', '0.0.0.0']:
                internal_host = 'acexy'
            
            # Use ACEXY_PORT for internal connection too
            start_url = f"http://{internal_host}:{ACEXY_PORT}/ace/getstream?id={ace_id}"
            logger.info(f"Connecting to AceXY (Internal): {internal_host}:{ACEXY_PORT}")

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
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.processes[ace_id] = proc
            self.activity[ace_id] = time.time()
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
                
                stream_dir = os.path.join(HLS_DIR, ace_id)
                if os.path.exists(stream_dir):
                    shutil.rmtree(stream_dir)

hls_manager = HLSManager()

class ChannelManager:
    def __init__(self):
        self.last_update = 0
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)

    def update_channels(self):
        """Downloads and processes the M3U list."""
        current_time = time.time()
        if current_time - self.last_update < CACHE_DURATION and os.path.exists(JSON_FILE):
            logger.info("Cache valid, skipping update.")
            return

        logger.info("Updating channels list...")
        try:
            requests.packages.urllib3.disable_warnings()
            response = requests.get(URL_ORIGEN, timeout=30, verify=False)
            response.raise_for_status()
            content = response.text
        except Exception as e:
            logger.error(f"Failed to download list: {e}")
            return

        lines = content.splitlines()
        channels = []
        new_m3u_content = ["#EXTM3U"]
        
        info_line = ""

        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            if line.startswith("#EXTINF:"):
                info_line = line
                continue
            
            if info_line:
                ace_id = None
                # Regex to extract AceStream ID
                match_ace = re.search(r'acestream://([a-f0-9]{40})', line)
                match_http = re.search(r'id=([a-f0-9]{40})', line)

                if match_ace:
                    ace_id = match_ace.group(1)
                elif match_http:
                    ace_id = match_http.group(1)

                if ace_id:
                    # Parse Meta (Name, Logo)
                    name = info_line.split(',')[-1].strip().replace(" [ACESTREAM]", "")
                    logo_match = re.search(r'tvg-logo="([^"]+)"', info_line)
                    logo = logo_match.group(1) if logo_match else ""
                    group_match = re.search(r'group-title="([^"]+)"', info_line)
                    group = group_match.group(1) if group_match else "General"

                    # Generate new stream URL for AceXY (Multiplexing Proxy)
                    # AceXY uses /ace/getstream?id=<id>
                    # It automagically handles multiplexing.
                    stream_url = f"http://{ACEXY_IP}:{ACEXY_PORT}/ace/getstream?id={ace_id}"
                    
                    # Add to JSON list
                    channels.append({
                        "id": ace_id,
                        "name": name,
                        "logo": logo,
                        "group": group,
                        "url": stream_url
                    })

                    # Add to M3U
                    new_m3u_content.append(info_line.replace(" [ACESTREAM]", ""))
                    new_m3u_content.append(stream_url)

                info_line = "" # Reset for next

        # Save results
        try:
            with open(JSON_FILE, 'w') as f:
                json.dump(channels, f, indent=2)
            
            with open(M3U_FILE, 'w') as f:
                f.write("\n".join(new_m3u_content))
            
            self.last_update = current_time
            logger.info(f"Update complete. {len(channels)} channels processed.")
        except Exception as e:
            logger.error(f"Error saving output files: {e}")

channel_manager = ChannelManager()

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/api/channels')
def get_channels():
    channel_manager.update_channels()
    if os.path.exists(JSON_FILE):
        with open(JSON_FILE, 'r') as f:
            data = json.load(f)
            
        # Dynamic URL replacement logic
        # If ACEXY_IP is a local/container reference, we substitute it with the request IP (Dynamic)
        # If ACEXY_IP is a specific external IP/Domain, we respect it (Static)
        host_ip = request.host.split(':')[0]
        
        target_ip = ACEXY_IP
        if ACEXY_IP in ['127.0.0.1', 'localhost', '0.0.0.0', 'acexy', 'acestream']:
            target_ip = host_ip

        for ch in data:
            if "url" in ch and ACEXY_IP in ch["url"]:
                 ch["url"] = ch["url"].replace(ACEXY_IP, target_ip)
            elif "url" in ch:
                # Reconstruct URL: http://<TARGET_IP>:<PORT>/ace/getstream?id=<ID>
                ch["url"] = f"http://{target_ip}:{ACEXY_PORT}/ace/getstream?id={ch['id']}"

        return jsonify(data)
    return jsonify([]), 500

@app.route('/api/version')
def get_version():
    try:
        with open('version.txt', 'r') as f:
            return jsonify({"version": f.read().strip()})
    except:
        return jsonify({"version": "dev"})

@app.route('/playlist.m3u')
def get_playlist():
    channel_manager.update_channels()
    
    if os.path.exists(JSON_FILE):
        try:
            with open(JSON_FILE, 'r') as f:
                channels = json.load(f)
            
            host_ip = request.host.split(':')[0]
            
            # Determine effective IP for streams
            target_ip = ACEXY_IP
            if ACEXY_IP in ['127.0.0.1', 'localhost', '0.0.0.0', 'acexy', 'acestream']:
                target_ip = host_ip
                
            m3u_lines = ["#EXTM3U"]
            
            for ch in channels:
                logo_attr = f' tvg-logo="{ch.get("logo", "")}"' if ch.get("logo") else ""
                group_attr = f' group-title="{ch.get("group", "")}"' if ch.get("group") else ""
                
                info_line = f'#EXTINF:-1{logo_attr}{group_attr},{ch["name"]}'
                
                ace_id = ch["id"]
                # Use target_ip (either dynamic or explicit)
                stream_url = f"http://{target_ip}:{ACEXY_PORT}/ace/getstream?id={ace_id}"
                
                m3u_lines.append(info_line)
                m3u_lines.append(stream_url)
                
            return Response("\n".join(m3u_lines), mimetype='audio/x-mpegurl')
        except Exception as e:
            logger.error(f"Error generating dynamic playlist: {e}")
            return "Error generating playlist", 500

    return "No channels available", 404

@app.route('/api/hls/start/<ace_id>')
def start_hls(ace_id):
    success = hls_manager.start_stream(ace_id)
    if success:
        # Wait a bit for the playlist to appear
        m3u8_path = os.path.join(HLS_DIR, ace_id, "index.m3u8")
        retries = 10
        while retries > 0:
            if os.path.exists(m3u8_path) and os.path.getsize(m3u8_path) > 0:
                return jsonify({"status": "ok", "url": f"/hls/{ace_id}/index.m3u8"})
            time.sleep(1)
            retries -= 1
        return jsonify({"status": "ok", "url": f"/hls/{ace_id}/index.m3u8", "note": "Stream starting, playlist may not be ready yet"})
    return jsonify({"status": "error"}), 500

@app.route('/api/hls/stop/<ace_id>')
def stop_hls(ace_id):
    hls_manager.stop_stream(ace_id)
    return jsonify({"status": "stopped"})

@app.route('/hls/<ace_id>/<filename>')
def serve_hls(ace_id, filename):
    hls_manager.update_activity(ace_id)
    return send_from_directory(os.path.join(HLS_DIR, ace_id), filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
