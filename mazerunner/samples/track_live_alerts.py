"""
This script will periodically query MazeRunner for new events and print them.
"""
import argparse
import sys
import time
import mazerunner

WAIT_TIME = 3  # Time to wait in seconds
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
                        type=str,
                        help="The file path to the SSL certificate of the "
                             "MazeRunner management server")
    parser.add_argument('-m', '--show-muted', action='store_true',
                        help="Show mute-level alerts as well as alert-level alerts")
    return parser.parse_args()


def main():
    """
    Here is what we do:

        * Parse command arguments.
        * Fetch all possible types of alerts.
        * Get an AlertCollection: show/hide muted alerts according to option specified in \
        the command, and show all types of alerts.
        * Check the current amount of alerts.
        * Periodically check for alerts and print the new ones.

    """
    args = get_args()

    client = mazerunner.connect(args.ip_address, args.api_key, args.api_secret, args.certificate)

    # Get alerts
    alert_types = client.alerts.params()['alert_type']
    last_seen_id = 0

    print("Showing all alerts live. Press Ctrl+C to exit.")

    try:
        while True:
            time.sleep(WAIT_TIME)
            alert_filter = client.alerts.filter(filter_enabled=True,
                                                only_alerts=not args.show_muted,
                                                alert_types=alert_types,
                                                id_greater_than=last_seen_id)

            for alert in alert_filter:
                print(DISPLAY_FORMAT.format(decoy_name=alert.decoy['name'],
                                            alert_type=alert.alert_type))

                if alert.id > last_seen_id:
                    last_seen_id = alert.id

    except KeyboardInterrupt:
        sys.exit()


if __name__ == '__main__':
    main()
