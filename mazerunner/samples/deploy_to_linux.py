"""
This sample script deploys (install/uninstall) a specific Deployment Group on linux endpoint[s]
supplied by the user. A unique endpoint can be provided from the command line, or use a csv file to
deploy on multiple endpoints.
"""
import tempfile
import mazerunner
import paramiko
import ntpath
import argparse
import csv
import os

HOST_KEY = 'host'
PORT_KEY = 'port'
USER_KEY = 'user'
PASS_KEY = 'pass'


def get_args():
    """
    Parse command arguments
    """

    parser = argparse.ArgumentParser()

    parser.add_argument('ip_address', type=str, help="IP address of MazeRunner management server.")
    parser.add_argument('api_key', type=str, help="The API key.")
    parser.add_argument('api_secret', type=str, help="The API secret.")
    parser.add_argument('deployment_type', type=str,
                        help='Specify which deployment we want to do - install/uninstall.',
                        choices=['install', 'uninstall'])
    parser.add_argument('deployment_group', type=str,
                        help='The name of the Deployment Group in MazeRunner.')
    parser.add_argument(
        '--certificate',
        type=str,
        help="The file path to the SSL certificate of the MazeRunner management server.")
    parser.add_argument('--ip', type=str, help='ip of a linux endpoint to deploy.')
    parser.add_argument('--port', type=int, help='ssh port of a linux endpoint - default to 22.',
                        default='22')
    parser.add_argument('--user', type=str, help='username of the linux endpoint to deploy.')
    parser.add_argument('--passwd', type=str, help='password of the linux endpoint to deploy.')
    parser.add_argument('--csv', type=str, help='Name of a CSV file, each line of the CSV should '
                                                'contain "HOST,IP,USER,PASS".')

    return parser.parse_args()


def init_ssh_client(host, port, user, passwd):
    """
    Init the SSClient and the SFTPClient.

    :param host: The ip of the endpoint we need to connect.
    :param port: The port of the endpoint.
    :param user: The user (should be root, or a user who can SUDO without password).
    :param passwd: The password for the user to connect to the endpoint.
    :return: (paramiko.SSHClient,  paramiko.SFTPClient).
    """
    sshclient = paramiko.SSHClient()
    sshclient.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    sshclient.connect(host, port, user, passwd, look_for_keys=False)
    transport = sshclient.get_transport()
    sftpclient = paramiko.SFTPClient.from_transport(transport)
    return sshclient, sftpclient


def run_cmd(ssh, cmd):
    """
    Tun a command on an existing ssh connection.

    :param ssh: ssh client.
    :param cmd: command to run.
    """
    stdin, stdout, stderr = ssh.exec_command(cmd)
    # we must read the out/err stream
    stdout.read()
    stderr.read()


def deploy_zip_on_endpoints(zipfile, endpoints, deploy_type, deployment_group):
    """
    Deploy (install/uninstall) the zipfile on each of the endpoints in the list.

    :param zipfile: String contains the full local path to the zipfile we need to upload.
    :param endpoints: List of the endpoints we need to deploy on.
    :param deploy_type: type of deployment - install/uninstall.
    :param deployment_group: the name of the deployment group we want to deploy, this param is used only for \
    printing the name.
    """
    for endpoint in endpoints:
        try:
            ssh, sftp = init_ssh_client(endpoint['host'], int(endpoint['port']), endpoint['user'], endpoint['pass'])
            sftp.put(zipfile, '/tmp/{}'.format(ntpath.basename(zipfile)))

            # Install unzip if not found
            install_zip_cmd = 'if [ "" == "`which unzip`" ]; ' \
                  'then echo "Unzip Not Found"; ' \
                  'if [ -n "`which apt-get`" ]; ' \
                  'then sudo apt-get -y install unzip ; ' \
                  'elif [ -n "`which yum`" ]; ' \
                  'then sudo yum -y install unzip ; ' \
                  'fi ; ' \
                  'fi'
            run_cmd(ssh, install_zip_cmd)

            # unzip the zip file
            unzip_file_cmd = 'cd /tmp; sudo unzip {} -d {}'.format(
                ntpath.basename(zipfile),
                ntpath.basename(zipfile)[:-4]
            )
            run_cmd(ssh, unzip_file_cmd)

            # chmod +x the setup file
            chmod_setup_cmd = 'sudo chmod +x /tmp/{}/setup.sh'.format(
                ntpath.basename(zipfile)[:-4]
            )
            run_cmd(ssh, chmod_setup_cmd)

            # run the setup file
            run_setup_cmd = 'sudo /tmp/{}/setup.sh'.format(
                ntpath.basename(zipfile)[:-4]
            )
            run_cmd(ssh, run_setup_cmd)

            # Delete the original zip file
            rm_file_cmd = 'sudo rm -rf {} {}'.format(zipfile, zipfile[:-4])
            run_cmd(ssh, rm_file_cmd)

            print("MazeRunner deployment group '{}' {}ed successfully on '{}'.".format(
                deployment_group,
                deploy_type,
                endpoint['host'])
            )

        except paramiko.ssh_exception.NoValidConnectionsError:
            print("Unable to {} on '{}:{}' - Unable to connect.".format(
                deploy_type,
                endpoint['host'],
                endpoint['port'])
            )
        except paramiko.ssh_exception.AuthenticationException:
            print("Unable to {} on '{}:{}' - Authentication failed.".format(
                deploy_type,
                endpoint['host'],
                endpoint['port'])
            )


def parse_csv_file(csv_file):
    """
    Parse a CSV file to a list of items.
    Each item is a dict contains an endpoint's data with the following values: host, port, user, pass.

    :param csv_file: Name of the CSV file to parse.
    :return: List
    """
    linux_endpoints_to_deploy = []
    if os.path.exists(csv_file):
        with open(csv_file, 'rb') as csvfile:
            endpoints_reader = csv.reader(csvfile)
            for row in endpoints_reader:
                if len(row) != 4:
                    raise Exception("Each row in the CSV file should contain exactly 4 values. "
                                    "Got {} instead.".format(len(row)))
                # Add values to the endpoints list
                linux_endpoints_to_deploy.append({
                    HOST_KEY: row[0], PORT_KEY: row[1], USER_KEY: row[2], PASS_KEY: row[3]
                })
        return linux_endpoints_to_deploy
    else:
        raise RuntimeError("CSV file not found.")


def main():
    args = get_args()
    linux_endpoints_to_deploy = []

    # Parse CSV file if we got one
    if args.csv:
        linux_endpoints_to_deploy = parse_csv_file(args.csv)
    elif args.ip and args.port and args.user and args.passwd:
        # save endpoint's specific data if we got it from the command line
        linux_endpoints_to_deploy.append({
            HOST_KEY: args.ip, PORT_KEY: args.port, USER_KEY: args.user, PASS_KEY: args.passwd
        })

    if not linux_endpoints_to_deploy:
        raise Exception("No endpoints found to work on.")

    # Init the MazeRunner client
    client = mazerunner.connect(args.ip_address, args.api_key, args.api_secret, args.certificate)

    # Get a new tempfile name
    dep_file = tempfile.mkdtemp()
    dep_file_full = "{}.zip".format(dep_file)

    # Get the deployment group we want to deploy
    deployment_groups = [deployment_group for deployment_group in client.deployment_groups
                         if deployment_group.name == args.deployment_group]
    if not deployment_groups:
        raise Exception("Deployment group names '{}' not found.".format(args.deployment_group))
    deployment_group = deployment_groups[0]

    # Create the deployment file
    deployment_group.deploy(dep_file, 'Linux', args.deployment_type, 'ZIP')

    # Deploy the file on all endpoints we have
    deploy_zip_on_endpoints(dep_file_full, linux_endpoints_to_deploy, args.deployment_type,
                            args.deployment_group)


if __name__ == "__main__":
    main()
