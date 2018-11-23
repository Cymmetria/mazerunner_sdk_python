"""
This sample script creates an SMB deception chain with a list of usernames supplied by the user,
each having a random password from a passwords file or from a predetermined password pool.
"""
import random
import argparse
import zipfile
import os
import tempfile
import time

import mazerunner


def _create_temp_file():
    """
    this function creates an empty temporary file and returns a path to the file
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

    with zipfile.ZipFile(zip_file_path, "w") as zip_file:
        zip_file.write(text_file_path)

    os.remove(text_file_path)

    return zip_file_path


def get_args():
    """
    Configure the command arguments parser
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('ip_address', type=str, help="IP address of MazeRunner management server")
    parser.add_argument('api_key', type=str, help="The API key")
    parser.add_argument('api_secret', type=str, help="The API secret")
    parser.add_argument('certificate',
                        type=str,
                        help="The file path to the SSL certificate "
                             "of the MazeRunner management server")
    parser.add_argument('usernames_file', type=str, help="The file path to a list of usernames")
    parser.add_argument('-p', '--passwords', required=False, type=str,
                        help="The file path to a list of passwords")
    return parser.parse_args()


def main():
    """
    Here is what we do:

        * Parse the command arguments.
        * Create a decoy named "Backup Server Decoy".
        * Wait until the decoy is created.
        * Create an SMB service.
        * Attach the SMB service to the decoy we previously created.
        * Load users & passwords data file.
        * Create breadcrumbs and attach them to the service we previously created.
        * Start the decoy machine.

    At the end of this process, we will have a nested (KVM) decoy.
    On that decoy, we will have an SMB service installed, which will have several SMB users.
    """
    args = get_args()

    # Connect to the MazeRunner API
    # The client object holds your session data and allows you to access the MazeRunner resources
    client = mazerunner.connect(args.ip_address, args.api_key, args.api_secret, args.certificate)

    # Create a decoy
    # This will create a decoy virtual machine inside MazeRunner.
    # The decoy acts as a trap,
    # Any action done on the decoy is monitored and will generate an alert on MazeRunner
    print "Creating Decoy"
    decoy = client.decoys.create(name="Backup Server Decoy", hostname="nas-backup-02",
                                 os="Ubuntu_1404", vm_type="KVM")
    while decoy.machine_status != "not_seen":  # make sure the decoy was created
        time.sleep(5)
        decoy.load()

    # Create a service
    # Different services allow you to mimic different resources you have on your network
    print "Creating service"
    smb_zip_file = _create_dummy_zip_file()
    service = client.services.create(name="SMB Serice", service_type="smb", share_name="accounting",
                                     zip_file_path=smb_zip_file)
    os.remove(smb_zip_file)

    # Connect the service to the decoy
    # When a service is connected to a decoy, you may access the service on the decoy.
    # Any such interaction will generate an alert
    print "Connecting service to decoy"
    service.connect_to_decoy(decoy.id)

    with open(args.usernames_file, 'r') as f:
        data = f.read()
        usernames = [u.strip() for u in data.split('\n') if u.strip()]

    if args.passwords:
        with open(args.passwords, 'r') as f:
            data = f.read()
            passwords = [p.strip() for p in data.split('\n') if p.strip()]
    else:
        passwords = ['pass', '1234', 'xyz', 'qwerty'] # default common passwords

    print "Creating Breadcrumbs"
    for idx, username in enumerate(usernames):
        # Create breadcrumb
        # Breadcrumbs can be deployed on endpoints to trick
        # an attacker to interact with a decoy and generate an alert
        breadcrumb = client.breadcrumbs.create(
            name="SMB Breadcrumb %d" % idx,
            breadcrumb_type="netshare",
            username=username,
            password=random.choice(passwords),
            persistence='persistent',
            registry_entry_name='test registry entry')

        # Connect the breadcrumb to the service
        # When a breadcrumb is connected to a service, the credential and other information
        # found in the breadcrumb will be usable with the service
        breadcrumb.connect_to_service(service.id)

    # Power the decoy on
    # After we set up the entire deception chain - its time to power on the decoy!
    decoy.power_on()

if __name__ == '__main__':
    main()
