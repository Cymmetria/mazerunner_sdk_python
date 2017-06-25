"""
This sample script runs a syslog server that will receive CEF messages and send them back
to MazeRunner's ActiveSOC using the API.
"""
import argparse
import requests
import re
import SocketServer
import mazerunner

HOST = "0.0.0.0"
PORT = 514
CEF_EVENT_FIELDS_DELIMITER = r'\|'
CEF_EVENT_EXPECTED_FIELDS = 8


class CEFError(RuntimeError):
    pass


class CEFEvent(object):
    def __init__(self, cef_version, device_vendor, device_product, device_version, signature_id,
                 name, severity, extra_data):
        self.cef_version = cef_version
        self.device_vendor = device_vendor
        self.device_product = device_product
        self.device_version = device_version
        self.signature_id = signature_id
        self.name = name
        self.severity = severity
        self.extra_data = extra_data

    @classmethod
    def parse_cef_str(cls, event_string):
        tokens = re.split(CEF_EVENT_FIELDS_DELIMITER, event_string)

        if len(tokens) != CEF_EVENT_EXPECTED_FIELDS:
            raise CEFError('Invalid event format')

        return cls(
            cef_version=cls._parse_cef_version(tokens[0]),
            device_vendor=tokens[1],
            device_product=tokens[2],
            device_version=tokens[3],
            signature_id=tokens[4],
            name=tokens[5],
            severity=tokens[6],
            extra_data=cls._parse_extra_data(tokens[7])
        )

    def to_json(self):
        data = {
            'cef_version': self.cef_version,
            'device_vendor': self.device_vendor,
            'device_product': self.device_product,
            'device_version': self.device_version,
            'signature_id': self.signature_id,
            'name': self.name,
            'severity': self.severity,
        }

        data.update(self.extra_data)
        return data

    @staticmethod
    def _parse_cef_version(cef_version_string):
        version_regex = re.compile('CEF:(?P<cef_ver>\d+)')
        match = version_regex.search(cef_version_string)

        if not match:
            raise CEFError('Invalid CEF version')

        return match.groupdict()['cef_ver']

    @staticmethod
    def _parse_extra_data(extra_data_string):
        params_regex = re.compile('(?P<key>[\w\d]+)=(?P<value>[^\s]*)')

        return {
            match['key']: match['value']
            for match
            in [
                match.groupdict()
                for match
                in re.finditer(params_regex, extra_data_string)
            ]
        }


def get_syslog_handler(client):
    class SyslogUDPHandler(SocketServer.BaseRequestHandler):
        def __init__(self, request, client_address, server):
            self._client = client
            SocketServer.BaseRequestHandler.__init__(self, request, client_address, server)

        def handle(self):
            data = bytes.decode(self.request[0])
            cef_data = CEFEvent.parse_cef_str(data).to_json()
            self._client.active_soc_events.create(soc_name='api-soc', event_dict=cef_data)
    return SyslogUDPHandler


def _suppress_ssl_errors():
    requests.packages.urllib3.disable_warnings(
        requests.packages.urllib3.exceptions.InsecureRequestWarning)


def get_args():
    """
    Parse command arguments
    """
    parser = argparse.ArgumentParser()

    parser.add_argument('ip_address', type=str, help="IP address of MazeRunner management server")
    parser.add_argument('api_key', type=str, help="The API key")
    parser.add_argument('api_secret', type=str, help="The API secret")
    parser.add_argument('--certificate', type=str, help="The file path to the SSL certificate of "
                                                        "the MazeRunner management server")

    return parser.parse_args()


def main():
    args = get_args()

    if not args.certificate:
        _suppress_ssl_errors()

    # Init the MazeRunner client
    client = mazerunner.connect(args.ip_address,
                                args.api_key,
                                args.api_secret,
                                args.certificate)

    try:
        server = SocketServer.UDPServer((HOST, PORT), get_syslog_handler(client))
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print ("Ctrl+C Pressed. Shutting down.")


if __name__ == "__main__":
    main()
