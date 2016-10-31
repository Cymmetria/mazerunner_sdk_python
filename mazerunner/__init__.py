from mazerunner import api_client


def connect(ip_address, api_key, api_secret, certificate, use_http=False):
    """Establish a connection to the MazeRunner server"""
    return api_client.APIClient(ip_address, 
                                api_key, 
                                api_secret, 
                                certificate,
                                use_http=use_http)
