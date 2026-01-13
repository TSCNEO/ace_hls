from app.config import Config

LOCAL_INDICATORS = ['127.0.0.1', 'localhost', '0.0.0.0', 'acexy', 'acestream']

def get_acexy_url_for_client(request_host, ace_id=None):
    """
    Determines the URL the browser should use to reach AceXY.
    If ACEXY_IP is configured as local, we assume AceXY is running 
    alongside the app and use the request's hostname.
    """
    target_ip = Config.ACEXY_IP
    
    # If AceXY is local, clients should connect to the same IP they used to access the web interface
    if Config.ACEXY_IP in LOCAL_INDICATORS:
        target_ip = request_host.split(':')[0]
        
    base_url = f"http://{target_ip}:{Config.ACEXY_PORT}/ace/getstream"
    if ace_id:
        return f"{base_url}?id={ace_id}"
    return base_url

def get_acexy_host_for_server():
    """
    Determines the hostname the server (Python/FFmpeg) should use to reach AceXY.
    If running in Docker and set to local, we use the container name 'acexy'.
    """
    internal_host = Config.ACEXY_IP
    if internal_host in ['127.0.0.1', 'localhost', '0.0.0.0']:
        internal_host = 'acexy'
    return internal_host
