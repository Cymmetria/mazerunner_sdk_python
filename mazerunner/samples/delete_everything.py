"""
This script will delete all of the entities on your MazeRunner system.
"""
import argparse
import mazerunner


def _delete_items_in_collection(collection, exclude_persist=False):
    for item in list(collection):
        if exclude_persist and getattr(item, "persist", False):
            continue
        item.delete()


def get_args():
    """
    Parse command arguments
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('ip_address', type=str, help="IP address of MazeRunner management server")
    parser.add_argument('api_key', type=str, help="The API key")
    parser.add_argument('api_secret', type=str, help="The API secret")
    parser.add_argument('certificate',
                        type=str, help="The file path to the SSL certificate of the "
                                       "MazeRunner management server")
    return parser.parse_args()


def main():
    """
    Here is what we do:

        * Parse command arguments.
        * Create MazeRunner connection.
        * Get a collection of all breadcrumbs.
        * Delete all elements in the collection.
        * Same for deployment groups, decoys, services, endpoints, cidr mappings, background tasks

    """
    args = get_args()

    client = mazerunner.connect(args.ip_address, args.api_key, args.api_secret, args.certificate)

    # Delete breadcrumbs:
    breadcrumbs = client.breadcrumbs
    print 'Deleting %d breadcrumbs' % len(breadcrumbs)
    _delete_items_in_collection(breadcrumbs)

    # Delete deployment groups:
    deployment_groups = client.deployment_groups
    print 'Deleting %d deployment groups' % len(deployment_groups)
    _delete_items_in_collection(deployment_groups, exclude_persist=True)

    # Delete services:
    services = client.services
    print 'Deleting %d services' % len(services)
    _delete_items_in_collection(services)
    
    # Delete decoys:
    decoys = client.decoys
    print 'Deleting %d decoys' % len(decoys)
    _delete_items_in_collection(decoys)

    # Delete CIDR mappings:
    cidr_mappings = client.cidr_mappings
    print 'Deleting %d cidr mappings' % len(cidr_mappings)
    _delete_items_in_collection(cidr_mappings)

    # Delete endpoints:
    endpoints = client.endpoints
    print 'Deleting %d endpoints' % len(endpoints)
    _delete_items_in_collection(endpoints)

    # Acknowledge all complete background tasks:
    print 'Acknowledging all complete background tasks'
    client.background_tasks.acknowledge_all_complete()


if __name__ == '__main__':
    main()
