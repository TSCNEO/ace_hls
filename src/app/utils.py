from app.config import Config

LOCAL_INDICATORS = ['127.0.0.1', 'localhost', '0.0.0.0', 'acexy', 'acestream']

def get_acexy_url_for_client(request_host, ace_id=None):
    """
    Determines the URL the browser should use to reach AceXY.
    If ACEXY_IP is configured as local, we assume AceXY is running 
    alongside the app and use the request's hostname.
    """
    # Priority 1: Public Endpoint (External/Custom Domain)
    if Config.ACEXY_PUBLIC_ENDPOINT:
        base_url = f"{Config.ACEXY_PUBLIC_ENDPOINT}/ace/getstream"
        
        # Build Query Params
        params = []
        if ace_id:
            params.append(f"id={ace_id}")
        if Config.ACEXY_PUBLIC_TOKEN:
            params.append(f"token={Config.ACEXY_PUBLIC_TOKEN}")
            
        if params:
            return f"{base_url}?" + "&".join(params)
        return base_url

    # Priority 2: Local Auto-Discovery (Docker network or same host)
    target_ip = Config.ACEXY_IP
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
