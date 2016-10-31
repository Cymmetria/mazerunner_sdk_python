"""
This script will delete all the entities on your MazeRunner system
"""
import argparse
import sys
import time
import mazerunner

WAIT_TIME = 3 # Time to wait in seconds
DISPLAY_FORMAT = '''Got a new alert!
Decoy: {decoy_name}
Alert Type: {alert_type}'''

def get_args():
    """
    Parse command arguments
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('ip_address', type=str, help="IP address of MazeRunner management server")
    parser.add_argument('api_key', type=str, help="The API key")
    parser.add_argument('api_secret', type=str, help="The API secret")
    parser.add_argument('certificate',
                        type=str, help="The file path to the SSL certificate of the MazeRunner management server")
    parser.add_argument('-m', '--show-muted', action='store_true',
                        help="Show mute-level alerts as well as alert-level alerts")
    return parser.parse_args()

def main():
    """
    Here's what we do:

        * Parse command arguments
        * Fetch all possible types of alerts.
        * Get an AlertCollection: show/hide muted alerts according to option specified in \
        the command, and show all types of alerts.
        * Check the current amount of alerts
        * Periodically check for alerts and print the new ones.

    """
    args = get_args()

    client = mazerunner.connect(args.ip_address, args.api_key, args.api_secret, args.certificate, False)

    # Get alerts
    alerts = client.alerts
    alert_types = alerts.params()['alert_type']
    filtered_alerts = alerts.filter(filter_enabled=True, only_alerts=not args.show_muted, alert_types=alert_types)
    print "Showing all alerts live. Press Ctrl+C to exit."
    last_length = len(list(filtered_alerts))
    try:
        while True:
            time.sleep(WAIT_TIME)
            current_length = len(list(filtered_alerts))
            if current_length > last_length:
                alert_list = list(filtered_alerts)
                for i in range(last_length, current_length):
                    print DISPLAY_FORMAT.format(
                        decoy_name=alert_list[i].decoy['name'], alert_type=alert_list[i].alert_type)
            last_length = current_length

    except KeyboardInterrupt:
        sys.exit()


if __name__ == '__main__':
    main()
