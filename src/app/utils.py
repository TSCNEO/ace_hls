from app.config import Config

LOCAL_INDICATORS = ['127.0.0.1', 'localhost', '0.0.0.0', 'acexy', 'acestream']

def get_acexy_url_for_client(request_host, ace_id=None, identifier_type="id"):
    """
    Determines the URL the browser should use to reach AceXY.
    """
    from app.services.settings_manager import settings_manager
    settings = settings_manager.get_all()
    
    public_endpoint = settings.get('acexy_public_endpoint')
    public_token = settings.get('acexy_public_token')

    # Priority 1: Public Endpoint (External/Custom Domain)
    if public_endpoint:
        base_url = f"{public_endpoint}/ace/getstream"
        
        # Build Query Params
        params = []
        if ace_id:
            query_key = "infohash" if identifier_type == "infohash" else "id"
            params.append(f"{query_key}={ace_id}")
        if public_token:
            params.append(f"token={public_token}")
            
        if params:
            return f"{base_url}?" + "&".join(params)
        return base_url

    # Priority 2: Local Auto-Discovery (Docker network or same host)
    target_ip = Config.ACEXY_IP
    if Config.ACEXY_IP in LOCAL_INDICATORS:
        target_ip = request_host.split(':')[0]
        
    base_url = f"http://{target_ip}:{Config.ACEXY_PORT}/ace/getstream"
    if ace_id:
        query_key = "infohash" if identifier_type == "infohash" else "id"
        return f"{base_url}?{query_key}={ace_id}"
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
