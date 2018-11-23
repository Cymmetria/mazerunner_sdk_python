"""
This sample script creates a deployment group with the requested breadcrumb type
and downloads the deployment package
"""
import random
import argparse
import zipfile
import os
import tempfile
import time

import mazerunner
from mazerunner.exceptions import ValidationError

COMMON_SAMPLE_PASSWORD = ['password', '12345678', 'xyzvbnm,', 'qwertyui']


def _create_temp_file():
    """
    This function creates an empty temporary file and returns a path to the file
    """
    temp_file = tempfile.mkstemp()
    os.close(temp_file[0])
    return temp_file[1]


def _create_dummy_zip_file():
    """
    This function creates a dummy zip file and returns a path to the file
    """
    text_file_path = _create_temp_file()
    zip_file_path = _create_temp_file()

    with zipfile.ZipFile(zip_file_path, 'w') as zip_file:
        zip_file.write(text_file_path)

    os.remove(text_file_path)

    return zip_file_path

DECOY_DATA = {
    'Windows Server': {
        'os': 'Windows_Server_2012',
        'name': 'Automated Decoy - Windows',
        'hostname': 'beijing-office',
        "vm_type": "KVM"
    },
    'Development Server': {
        'os': 'Ubuntu_1404',
        'name': 'Automated Decoy - Dev',
        'hostname': 'test-server',
        "vm_type": "KVM"
    },
    'DMZ Server': {
        'os': 'Ubuntu_1404',
        'name': 'Automated Decoy - DMZ',
        'hostname': 'office-access',
        "vm_type": "KVM"
    },
}

BREADCRUMB_DATA = {
    'cookie': {
        'requires_username': False,
        'requires_password': False,
        'args': {'browser': 'chrome', 'subservice': 'phpmyadmin'},
        'required_service': {'type': 'http', 'decoy': 'DMZ Server', 'args': {
            'web_apps': ['phpmyadmin'], 'zip_file_path': _create_dummy_zip_file()
        }}
    },
    'credentials': {
        'requires_username': True,
        'requires_password': True,
        'args': {},
        'required_service': {'type': 'smb', 'decoy': 'Windows Server', 'args': {
            'share_name': 'transfer_files', 'zip_file_path': _create_dummy_zip_file()
        }}
    },
    'git': {
        'requires_username': True,
        'requires_password': True,
        'args': {},
        'required_service': {'type': 'git', 'decoy': 'Development Server', 'args': {
            'repository_name': 'backend', 'zip_file_path': _create_dummy_zip_file()
        }}
    },
    'mysql': {
        'requires_username': True,
        'requires_password': True,
        'args': {'deploy_for': 'root', 'installation_type': 'mysql_history'},
        'required_service':{'type': 'mysql', 'decoy': 'Development Server', 'args': {}}
    },
    'netshare': {
        'requires_username': True,
        'requires_password': True,
        'args': {'persistence': 'non_persistent'},
        'required_service': {'type': 'smb', 'decoy': 'Windows Server', 'args': {
            'share_name': 'transfer_files', 'zip_file_path': _create_dummy_zip_file()
        }}
    },
    'openvpn': {
        'requires_username': True,
        'requires_password': True,
        'args': {'network_name': 'office'},
        'required_service': {'type': 'openvpn', 'decoy': 'DMZ Server', 'args': {
            'cert_country': 'US',
            'cert_state': 'CA',
            'cert_city': 'San Francisco',
            'cert_org': None,
            'cert_ou': None
        }}
    },
    'rdp': {
        'requires_username': True,
        'requires_password': True,
        'args': {},
        'required_service': {'type': 'rdp', 'decoy': 'Windows Server', 'args': {}}
    },
    'ssh': {
        'requires_username': True,
        'requires_password': True,
        'args': {},
        'required_service': {'type': 'ssh', 'decoy': 'DMZ Server', 'args': {}}
    },
    'ssh_privatekey': {
        'requires_username': True,
        'requires_password': False,
        'args': {'deploy_for': 'root', 'installation_type': 'alias'},
        'required_service': {'type': 'ssh', 'decoy': 'DMZ Server', 'args': {}}
    },
}

SERVICE_NAME = 'Automated %s service'
BREADCRUMB_NAME = 'Automated %s breadcrumb - %s'


def get_args():
    """
    Configure command arguments parser.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('ip_address', type=str, help='IP address of MazeRunner management server')
    parser.add_argument('api_key', type=str, help='The API key')
    parser.add_argument('api_secret', type=str, help='The API secret')
    parser.add_argument('certificate',
                        type=str,
                        help='The file path to the SSL certificate of the '
                             'MazeRunner management server')
    parser.add_argument('deployment_group_name',
                        type=str,
                        help='The name of the deployment group to be created')
    parser.add_argument('username',
                        type=str,
                        help='The username that will be shared among the breadcrumbs')
    parser.add_argument('breadcrumb_type', type=str, choices=BREADCRUMB_DATA.keys())
    parser.add_argument('-p',
                        '--passwords',
                        required=False,
                        type=str,
                        help='The file path to a list of passwords')
    parser.add_argument('-f',
                        '--format',
                        required=False,
                        type=str,
                        choices=['ZIP', 'EXE', 'MSI'],
                        default='ZIP',
                        help='The file format for the deployment script pack')
    return parser.parse_args()


def _get_password(passwords_file):
    """
    :param passwords_file: Local path of a password file
    """
    if passwords_file:
        with open(passwords_file, 'r') as f:
            data = f.read()
            passwords = [p.strip() for p in data.split('\n') if p.strip()]
    else:
        passwords = COMMON_SAMPLE_PASSWORD

    return random.choice(passwords)


def create_decoy_if_needed(client, decoy_key):
    """
    Create and power on a decoy, if non exist already.

    Decoys are virtual machines, to which we want to attract the attacker.

    :param client: An existing connection (the result of mazerunner.connect).
    :param decoy_key: The key in the DECOY_DATA hash of the desired decoy.
    """
    decoy_data = DECOY_DATA[decoy_key]
    decoys = [decoy for decoy in list(client.decoys) if decoy.name == decoy_data['name']]
    if decoys:
        decoy = decoys[0]
    else:
        print "Creating decoy: %s" % decoy_key
        decoy = client.decoys.create(**decoy_data)
        while decoy.machine_status != "not_seen":  # make sure the decoy was created
            time.sleep(5)
            decoy.load()

    if decoy.machine_status in ('not_seen', 'inactive'):
        decoy.power_on()

    return decoy


def create_service_if_needed(client, service_data):
    """
    Create a service.

    Services are applications installed on the decoys, to which we would like the attacker
    to try to log in.

    :param client: An existing connection (the result of mazerunner.connect).
    :param service_data: Arguments for the service configuration.
    """
    service_type = service_data['type']
    service_name = SERVICE_NAME % service_type

    services = [service for service in list(client.services) if service.name == service_name]
    if services:
        service = services[0]
    else:
        print "Creating %s service" % service_type
        args = service_data['args']
        args['service_type'] = service_type
        args['name'] = service_name
        service = client.services.create(**args)

    if 'zip_file_path' in service_data['args'] and \
            os.path.exists(service_data['args']['zip_file_path']):
        os.remove(service_data['args']['zip_file_path'])

    decoy = create_decoy_if_needed(client, service_data['decoy'])

    if decoy.id not in [decoy.id for decoy in list(service.attached_decoys)]:
        service.connect_to_decoy(decoy.id)

    return service


def create_breadcrumb(client, breadcrumb_type, breadcrumb_data, username, password, group_name):
    """
    Create a breadcrumb.

    A breadcrumb consists of connection credentials deployed on an endpoint. An attacker will find
    and use these credentials to connect to a service on a decoy.

    :param client: An existing connection (the result of mazerunner.connect).
    :param breadcrumb_type: Browser cookie, MySQL connection command, SMB path, etc.
    :param breadcrumb_data: Breadcrumb configuration dict.
    :param username: The user we would like to create on the service, which the attacker is \
    intended to find and use.
    :param password: The password of that user.
    :param group_name: A deployment group to which the breadcrumb should belong.
    """
    print "Creating %s breadcrumb" % breadcrumb_type
    args = breadcrumb_data['args']
    args['breadcrumb_type'] = breadcrumb_type
    args['name'] = BREADCRUMB_NAME % (breadcrumb_type, group_name)
    if breadcrumb_data['requires_username']:
        args['username'] = username
    if breadcrumb_data['requires_password']:
        args['password'] = password

    breadcrumb = client.breadcrumbs.create(**args)
    service = create_service_if_needed(client, breadcrumb_data['required_service'])
    breadcrumb.connect_to_service(service.id)

    return breadcrumb


def main():
    """
    Here's the procedure:

        * Parse the command args.
        * Configure connection to MazeRunner; store in the 'client' variable.
        * Create a deployment group (which is a logical group of breadcrumbs).
        * Create the breadcrumbs and their required services and decoy (see create_breadcrumb, \
            create_service_if_needed, create_decoy_if_needed).
        * Load the deployment group info from the server; wait for all the info to arrive.
        * Deploy the deployment groups.
    """
    args = get_args()

    client = mazerunner.connect(args.ip_address, args.api_key, args.api_secret, args.certificate)

    password = _get_password(args.passwords)

    deployment_group = client.deployment_groups.create(name=args.deployment_group_name)

    breadcrumb = create_breadcrumb(
        client,
        args.breadcrumb_type,
        BREADCRUMB_DATA[args.breadcrumb_type],
        args.username,
        password,
        args.deployment_group_name)
    breadcrumb.add_to_group(deployment_group.id)

    print "Waiting for deployment group to become available - this may take a few minutes"

    deployment_group.load()
    while not deployment_group.is_active:
        time.sleep(5)
        deployment_group.load()

    save_to = '%s' % args.deployment_group_name

    for operating_system in ['Windows', 'Linux']:
        try:
            deployment_group.deploy(
                location_with_name='%s_%s' % (save_to, operating_system),
                os=operating_system,
                download_type="install",
                download_format=args.format)
        except ValidationError:
            print 'This breadcrumb is not supported on %s, skipping' % operating_system

        print "%s deployment package saved to %s.%s" % (operating_system,
                                                        save_to,
                                                        args.format.lower())

if __name__ == '__main__':
    main()
