import os
import json
import re
import time
import requests
import logging
from app.config import Config

logger = logging.getLogger(__name__)

class ChannelManager:
    def __init__(self):
        self.last_update = 0
        if not os.path.exists(Config.DATA_DIR):
            os.makedirs(Config.DATA_DIR)

    def update_channels(self):
        """Downloads and processes the M3U list with cache check."""
        current_time = time.time()
        if os.path.exists(Config.JSON_FILE) and (current_time - self.last_update < Config.CACHE_DURATION):
             # Also check file modification time in case we restarted? 
             # Or just trust in-memory last_update + file existence.
             # If file exists but we just restarted, last_update is 0, so we update. That's good.
             return

        logger.info("Updating channels list...")
        try:
            requests.packages.urllib3.disable_warnings()
            response = requests.get(Config.URL_ORIGEN, timeout=30, verify=False)
            response.raise_for_status()
            content = response.text
        except Exception as e:
            logger.error(f"Failed to download list: {e}")
            return

        lines = content.splitlines()
        channels = []
        new_m3u_content = ["#EXTM3U"]
        
        info_line = ""

        # Using class-level or config access for IP not needed here as we use dynamic replacement 
        # But we still generate a base URL for 'url' field.
        # We will use the configured ACEXY_IP for the base JSON (server-side view)
        
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

                    # Generate new stream URL
                    stream_url = f"http://{Config.ACEXY_IP}:{Config.ACEXY_PORT}/ace/getstream?id={ace_id}"
                    
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

        # Save results safely
        try:
            # Atomic write pattern could be better but simple write is okay for now
            with open(Config.JSON_FILE, 'w') as f:
                json.dump(channels, f, indent=2)
            
            with open(Config.M3U_FILE, 'w') as f:
                f.write("\n".join(new_m3u_content))
            
            self.last_update = time.time()
            logger.info(f"Update complete. {len(channels)} channels processed.")
        except Exception as e:
            logger.error(f"Error saving output files: {e}")

# Global Instance
channel_manager = ChannelManager()
