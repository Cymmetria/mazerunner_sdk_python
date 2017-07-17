"""
This script will allow you to integrate the Responder feature in MazeRunner with ElasticSearch.
For usage information, run the script with no params.
"""


import argparse
import json
import os
from time import sleep, time
import requests
import mazerunner

SAMPLE_INTERVAL_SECONDS = 60

ELASTIC_SEARCH_URL_TEMPLATE = '{elastic_search_base_url}/{index}/{event_type}/_search?q={query}'

HIT_DATA_KEY = '_source'
HIT_MESSAGE_KEY = 'Message'
MSG_HITS_KEY = 'hits'

FIELD_USERNAME = 'username'
FIELD_DOMAIN = 'domain'
FIELD_ENDPOINT_IP = 'endpoint_ip'
FIELD_ENDPOINT_HOSTNAME = 'endpoint_hostname'
FIELD_EVENT_CODE = 'event_code'

EVENT_USERNAME_KEY = 'TargetUserName'
EVENT_DOMAIN_KEY = 'TargetDomainName'
EVENT_ATTACKED_ENDPOINT_KEY = 'hostname'

CONFIG_FILE = 'config.json'
CONFIG_MAZERUNNER_SERVER_KEY = 'mazerunner_server'
CONFIG_MAZERUNNER_API_ID_KEY = 'mazerunner_api_id'
CONFIG_MAZERUNNER_API_SECRET_KEY = 'mazerunner_api_secret'
CONFIG_MAZERUNNER_CERT_PATH_KEY = 'mazerunner_cert_path'
CONFIG_MAZERUNNER_SOC_API_INTERFACE_NAME_KEY = 'mazerunner_soc_api_interface_name'
CONFIG_ELASTIC_SEARCH_BASE_URL_KEY = 'elastic_search_base_url'
CONFIG_ELASTIC_SEARCH_INDEX_KEY = 'elastic_search_index'
CONFIG_ELASTIC_SEARCH_EVENT_TYPE_KEY = 'elastic_search_event_type'
CONFIG_MAZERUNNER_RESPONDER_USERS_KEY = 'mazerunner_responder_users'
CONFIG_RESPONDER_USERS_USER_KEY = 'user'
CONFIG_RESPONDER_USERS_DOMAIN_KEY = 'domain'

ELASTIC_SEARCH_CATEGORY_QUERY_KEY = 'Category'
ELASTIC_SEARCH_TIMESTAMP_QUERY_TEMPLATE = '@timestamp:[{from_ts} TO {to_ts}]'

WINDOWS_LOGON_EVENT = 'Logon'
WINDOWS_LOGON_FAILURE_EVENT_CODE = 529


def _get_current_timestamp():
    return int(time() * 1000)


def _extract_hit_info(hit):

    if HIT_DATA_KEY not in hit:
        return

    hit_data = hit.get(HIT_DATA_KEY)

    return {
        FIELD_USERNAME: hit_data.get(EVENT_USERNAME_KEY),
        FIELD_DOMAIN: hit_data.get(EVENT_DOMAIN_KEY),
        FIELD_ENDPOINT_IP: hit_data.get(EVENT_ATTACKED_ENDPOINT_KEY),
        FIELD_ENDPOINT_HOSTNAME: hit_data.get(EVENT_ATTACKED_ENDPOINT_KEY),
        FIELD_EVENT_CODE: WINDOWS_LOGON_FAILURE_EVENT_CODE
    }


def _build_users_condition(users_data):

    def _build_single_user_condition(user_data):
        user_condition = ElasticSearchValueCondition(
            key=EVENT_USERNAME_KEY,
            value=user_data.get(CONFIG_RESPONDER_USERS_USER_KEY))

        domain_condition = ElasticSearchValueCondition(
            key=EVENT_DOMAIN_KEY,
            value=user_data.get(CONFIG_RESPONDER_USERS_DOMAIN_KEY, ''))

        return ElasticSearchLogicalQueryAND([user_condition, domain_condition])

    return ElasticSearchLogicalQueryOR([
        _build_single_user_condition(user)
        for user
        in users_data
    ])


def _build_query(config, from_ts):
    category_condition = ElasticSearchValueCondition(
        key=ELASTIC_SEARCH_CATEGORY_QUERY_KEY,
        value=WINDOWS_LOGON_EVENT)

    time_range_condition = ElasticSearchTimeRangeCondition(
        from_ts=from_ts,
        to_ts=_get_current_timestamp())

    users_condition = _build_users_condition(config.mazerunner_responder_users)

    return ElasticSearchLogicalQueryAND([category_condition, time_range_condition, users_condition])


def fetch_events(config, from_ts):

    elastic_search_query_url = ELASTIC_SEARCH_URL_TEMPLATE.format(
            elastic_search_base_url=config.elastic_search_base_url,
            index=config.elastic_search_index,
            event_type=config.elastic_search_event_type,
            query=_build_query(config, from_ts).to_query_string()
        )

    try:
        print 'Requesting: %s' % elastic_search_query_url
        response = json.loads(requests.get(elastic_search_query_url).content)
    except ValueError:
        return []

    if not response.get(MSG_HITS_KEY) or not response[MSG_HITS_KEY].get(MSG_HITS_KEY):
        return []

    return filter(None, [_extract_hit_info(hit) for hit in response[MSG_HITS_KEY][MSG_HITS_KEY]])


def emit_events(config, events):
    client = mazerunner.connect(ip_address=config.mazerunner_server,
                                api_key=config.mazerunner_api_id,
                                api_secret=config.mazerunner_api_secret,
                                certificate=config.mazerunner_cert_path)
    client.active_soc_events.create_multiple_events(
        soc_name=config.mazerunner_soc_api_interface_name,
        events_dicts=events
    )


def run_monitor(config):
    last_run_ts = _get_current_timestamp()

    while True:
        sleep(SAMPLE_INTERVAL_SECONDS)
        events = fetch_events(config, last_run_ts)
        last_run_ts = _get_current_timestamp()
        print 'Found %s events' % len(events)
        if events:
            emit_events(config, events)


class EmptyQueryError(RuntimeError):
    pass


class ElasticSearchCondition(object):
    def to_query_string(self):
        raise NotImplementedError


class ElasticSearchValueCondition(ElasticSearchCondition):
    def __init__(self, key, value):
        self.key = key
        self.value = value

    def to_query_string(self):
        return '{key}:{value}'.format(key=self.key, value=self.value)


class ElasticSearchTimeRangeCondition(ElasticSearchCondition):
    def __init__(self, from_ts, to_ts):
        self.from_ts = from_ts
        self.to_ts = to_ts

    def to_query_string(self):
        return ELASTIC_SEARCH_TIMESTAMP_QUERY_TEMPLATE.format(
            from_ts=self.from_ts,
            to_ts=self.to_ts
        )


class ElasticSearchLogicalQueryGroup(object):
    DELIMITER = None

    def __init__(self, conditions):
        self._conditions = conditions

    def to_query_string(self):

        if not self._conditions:
            raise EmptyQueryError

        if not self.DELIMITER:
            raise NotImplementedError

        return '(%s)' % self.DELIMITER.join([condition.to_query_string()
                                             for condition
                                             in self._conditions])


class ElasticSearchLogicalQueryAND(ElasticSearchLogicalQueryGroup):
    DELIMITER = ' AND '


class ElasticSearchLogicalQueryOR(ElasticSearchLogicalQueryGroup):
    DELIMITER = ' OR '


class Config(object):
    def __init__(self, config_file):
        with open(config_file, 'rb') as f:
            config = json.load(f)

        self.mazerunner_server = config.get(CONFIG_MAZERUNNER_SERVER_KEY)
        self.mazerunner_api_id = config.get(CONFIG_MAZERUNNER_API_ID_KEY)
        self.mazerunner_api_secret = config.get(CONFIG_MAZERUNNER_API_SECRET_KEY)
        self.mazerunner_cert_path = config.get(CONFIG_MAZERUNNER_CERT_PATH_KEY)
        self.mazerunner_soc_api_interface_name = \
            config.get(CONFIG_MAZERUNNER_SOC_API_INTERFACE_NAME_KEY)
        self.mazerunner_responder_users = config.get(CONFIG_MAZERUNNER_RESPONDER_USERS_KEY)

        self.elastic_search_base_url = config.get(CONFIG_ELASTIC_SEARCH_BASE_URL_KEY)
        self.elastic_search_index = config.get(CONFIG_ELASTIC_SEARCH_INDEX_KEY)
        self.elastic_search_event_type = config.get(CONFIG_ELASTIC_SEARCH_EVENT_TYPE_KEY)

    @staticmethod
    def get_example():
        data = {
            CONFIG_MAZERUNNER_SERVER_KEY: 'serv',
            CONFIG_MAZERUNNER_API_ID_KEY: 'keykeykeykey',
            CONFIG_MAZERUNNER_API_SECRET_KEY: 'secretsecretsecretsecretsecret',
            CONFIG_MAZERUNNER_CERT_PATH_KEY: '/home/ubuntu/MazeRunner.crt',
            CONFIG_MAZERUNNER_SOC_API_INTERFACE_NAME_KEY: 'elasticsearch_interface',
            CONFIG_MAZERUNNER_RESPONDER_USERS_KEY: [{
                CONFIG_RESPONDER_USERS_USER_KEY: 'admin1',
                CONFIG_RESPONDER_USERS_DOMAIN_KEY: 'myorg.local'
            }, {
                CONFIG_RESPONDER_USERS_USER_KEY: 'admin2',
                CONFIG_RESPONDER_USERS_DOMAIN_KEY: 'myorg.local'
            }],
            CONFIG_ELASTIC_SEARCH_BASE_URL_KEY: 'http://mykibana:9200',
            CONFIG_ELASTIC_SEARCH_INDEX_KEY: 'security-*',
            CONFIG_ELASTIC_SEARCH_EVENT_TYPE_KEY: 'events'
        }

        return json.dumps(data, sort_keys=True, indent=4)


if __name__ == '__main__':

    parser = argparse.ArgumentParser(
        usage='\n'
              'This script should be used together with the Responder feature of MazeRunner.\n'
              'The Responder breadcrumb and service detect Responder.py tool usage in your '
              'network.\n'
              'When MazeRunner detects such tool it feeds it with the credentials you configured\n'
              'in the breadcrumb.\n'
              'As soon as the attacker tries to use these stolen credentials and log in\n'
              'to one of the monitored assets in your network,\n'
              'the event will be logged and sent to ElasticSearch. This script will find\n'
              'the event in ElasticSearch and send it to MazeRunner. For other products,\n'
              'like Splunk, MazeRunner already has a built-in integration.\n\n'
              'In order to use this script, please configure the following:\n\n'
              '1. Open the ActiveSOC tab in MazeRunner.\n'
              'Under "SOC Interfaces" click "add", choose "SOC via MazeRunner API" and\n'
              'give it a name (we named it "elasticsearch_responder" in the example below).\n\n'
              '2. In the Settings tab, go to the "API Keys" sub-tab. There, generate an api \n'
              'key-secret pair, and download the certificate to your computer.\n\n'
              '3. Create a responder campaign. For more information about this step,\n'
              'see the "ActiveSoc and responder monitor activity feed" section in the user '
              'manual.\n\n'
              '4. Under the ActiveSOC tab, go to "Responder Monitor", and make sure '
              'that "Responder monitor SOC integration" is activated.\n\n'
              '5. Create a configuration file and pass the file name as the first parameter for \n'
              'this script. Here is an example for the file:\n\n %s' % Config.get_example())
    parser.add_argument('config_file')
    args = parser.parse_args()

    if not os.path.isfile(args.config_file):
        print 'Error: %s file is missing. Please use the following example:' % args.config_file
        print Config.get_example()
        exit(1)

    run_monitor(Config(args.config_file))
