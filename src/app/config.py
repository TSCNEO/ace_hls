import os

class Config:
    # AceHLS Settings
    ACE_HLS_PORT = int(os.environ.get("ACE_HLS_PORT", 8088))
    CACHE_DURATION = int(os.environ.get("CACHE_DURATION", 300))
    # Use absolute path to avoid confusion with send_from_directory
    DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
    
    # External Resources
    URL_ORIGEN = os.environ.get("URL_ORIGEN", "https://ipfs.io/ipns/k2k4r8oqlcjxsritt5mczkcn4mmvcmymbqw7113fz2flkrerfwfps004/data/listas/lista_iptv.m3u")
    
    # AceXY Connection
    ACEXY_IP = os.environ.get("ACEXY_IP", "127.0.0.1")
    ACEXY_PORT = os.environ.get("ACEXY_PORT", "8080")

    # Paths
    JSON_FILE = os.path.join(DATA_DIR, "channels.json")
    SOURCES_FILE = os.path.join(DATA_DIR, "sources.json")
    M3U_FILE = os.path.join(DATA_DIR, "ace_hls.m3u")
    HLS_DIR = os.path.join(DATA_DIR, "hls")
