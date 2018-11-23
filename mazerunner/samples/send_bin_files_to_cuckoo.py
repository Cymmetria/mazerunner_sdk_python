#!/usr/bin/env python2

import argparse
import requests
import os
import tempfile
import shutil

import mazerunner


def retrieve_files_from_mazerunner(client, dirpath):

    const_bin = ".bin"

    # Create a list to store our files in
    alert_files = []

    # Grab Code Execution Alerts
    filter_params = dict(
        filter_enabled = True,
        only_alerts = False,
        alert_types = ["code","unsigned_code"]
    )
    alerts = client.alerts.filter(**filter_params)

    # Iterate through our alerts and download the bin files if one exists

    for alert in alerts:

        # Remove the extension as its added when we download the file from MazeRunner
        dest_file_name = alert.image_file_name

        # Local filepath where we will store our executable
        dest_file_path = os.path.join(dirpath, "%s_%s" % (alert.decoy["hostname"], dest_file_name))

        try:
            alert.download_image_file(dest_file_path[:-len(const_bin)])

            # Store path for later use
            alert_files.append(dest_file_path)

        except mazerunner.exceptions.ValidationError:
            # No file to download
            pass

    return alert_files


def send_files_to_cuckoo(cuckoo_api, verify_ssl, alert_files):

    # Iterate through our file list and send them to Cuckoo
    for current_file in alert_files:
        fname = os.path.basename(current_file)
        cuckoo_url = 'https://%s/tasks/create/file' % cuckoo_api

        try:
            with open(current_file, "rb") as sample:
                files = {"file": (fname, sample)}
                r = requests.post(cuckoo_url, files=files, verify=verify_ssl)

                # Ensure we successfully sent our file to Cuckoo
                if r.status_code != 200:
                    print "Error uploading file:" + fname
                    continue
        except IOError:
            print current_file + " could not be opened for reading."
            pass


def transfer_files_to_cuckoo(cuckoo_api, verify_ssl, connection_params):

    # Create a temporary directory to store our bin files in
    dirpath = tempfile.mkdtemp()

    try:
        # Instantiate our MazeRunner connection
        client = mazerunner.connect(**connection_params)

        # Download files from MazeRunner, Upload files to Cuckoo
        alert_files = retrieve_files_from_mazerunner(client, dirpath)
        send_files_to_cuckoo(cuckoo_api, verify_ssl, alert_files)

    finally:
        # Clean up after our work
        shutil.rmtree(dirpath)

    print "Process complete"


def main():
    parser = argparse.ArgumentParser("Send code execution files from MazeRunner to a Cuckoo Instance")
    parser.add_argument('mazerunner', help="IP address of MazeRunner management server")
    parser.add_argument('api_key', help="API key")
    parser.add_argument('api_secret', help="API secert key")
    parser.add_argument('certificate', help="Path to MazeRunner's SSL certificate")
    parser.add_argument('cuckoo_api', help="IP or FQDN of Cuckoo (192.168.1.10:4343 or cuckoo.yourdomain.com:4343")
    parser.add_argument('--skip-verification', dest='verify_ssl', action='store_false', help='Skip SSL verification')

    args = parser.parse_args()

    connection_params = dict(ip_address=args.mazerunner,
                             api_key=args.api_key,
                             api_secret=args.api_secret,
                             certificate=args.certificate
                             )

    transfer_files_to_cuckoo(args.cuckoo_api, args.verify_ssl, connection_params)


if __name__ == '__main__':
    main()