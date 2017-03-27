from mazerunner import api_client


def connect(ip_address, api_key, api_secret, certificate):
    """Establish a connection to the MazeRunner server"""
    return api_client.APIClient(ip_address, 
                                api_key, 
                                api_secret, 
                                certificate)
