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
        """Downloads and processes the M3U list from ALL sources with deduplication."""
        from app.services.source_manager import source_manager
        
        # We don't check for cache duration strictly here anymore because
        # we might have added a new source and want immediate update.
        # But to respect cache, we could check if any source changed?
        # For simplicity in this "v2", let's trust the caller (scheduler or manual)
        # or just enforce a small cooldown if needed. 
        # For now, we proceed to update.

        logger.info("Updating channels list from all sources...")
        
        sources = source_manager.get_sources()
        all_channels = []
        seen_ids = set()
        new_m3u_content = ["#EXTM3U"]
        
        requests.packages.urllib3.disable_warnings()

        for src in sources:
            url = src['url']
            try:
                logger.info(f"Fetching source: {url}")
                response = requests.get(url, timeout=30, verify=False)
                response.raise_for_status()
                content = response.text
                
                self._parse_m3u_content(content, url, all_channels, seen_ids, new_m3u_content)
                
            except Exception as e:
                logger.error(f"Failed to download list from {url}: {e}")
                # Continue to next source

        # Save results safely
        try:
            with open(Config.JSON_FILE, 'w') as f:
                json.dump(all_channels, f, indent=2)
            
            with open(Config.M3U_FILE, 'w') as f:
                f.write("\n".join(new_m3u_content))
            
            self.last_update = time.time()
            logger.info(f"Update complete. Total: {len(all_channels)} channels from {len(sources)} sources.")
        except Exception as e:
            logger.error(f"Error saving output files: {e}")

    def _parse_m3u_content(self, content, source_url, channels_list, seen_ids, m3u_lines):
        lines = content.splitlines()
        info_line = ""
        
        # Stats for this source
        stats = {"added": 0, "duplicates": 0, "total_found": 0}
        
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
                    stats["total_found"] += 1
                    # Deduplication check
                    if ace_id in seen_ids:
                        # Skip duplicate
                        stats["duplicates"] += 1
                        info_line = ""
                        continue
                        
                    seen_ids.add(ace_id)
                    stats["added"] += 1

                    # Parse Meta (Name, Logo)
                    name = info_line.split(',')[-1].strip().replace(" [ACESTREAM]", "")
                    logo_match = re.search(r'tvg-logo="([^"]+)"', info_line)
                    logo = logo_match.group(1) if logo_match else ""
                    group_match = re.search(r'group-title="([^"]+)"', info_line)
                    group = group_match.group(1) if group_match else "General"

                    # Generate new stream URL
                    stream_url = f"http://{Config.ACEXY_IP}:{Config.ACEXY_PORT}/ace/getstream?id={ace_id}"
                    
                    # Add to JSON list
                    channels_list.append({
                        "id": ace_id,
                        "name": name,
                        "logo": logo,
                        "group": group,
                        "url": stream_url,
                        "source": source_url # Track origin for debugging
                    })

                    # Add to M3U
                    m3u_lines.append(info_line.replace(" [ACESTREAM]", ""))
                    m3u_lines.append(stream_url)

                info_line = "" # Reset for next
        
        logger.info(f"Source Processed: {source_url} | Found: {stats['total_found']} | Added: {stats['added']} | Duplicates: {stats['duplicates']}")

# Global Instance
channel_manager = ChannelManager()
