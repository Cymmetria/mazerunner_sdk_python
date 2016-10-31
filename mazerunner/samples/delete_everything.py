"""
This script will delete all the entities on your MazeRunner system
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
                        type=str, help="The file path to the SSL certificate of the MazeRunner management server")
    return parser.parse_args()

def main():
    """
    Here's what we do:

        * Parse command arguments
        * Create MazeRunner connection
        * Get a collection of all breadcrumbs
        * Delete all elements in the collection
        * Same for services
        * Same for decoys

    """
    args = get_args()

    client = mazerunner.connect(args.ip_address, args.api_key, args.api_secret, args.certificate, False)

    # delete breadcrumbs:
    breadcrumbs = client.breadcrumbs
    print 'deleting %d breadcrumbs' % len(breadcrumbs)
    _delete_items_in_collection(breadcrumbs)

    # delete deployment groups:
    deployment_groups = client.deployment_groups
    print 'deleting %d deployment groups' % len(deployment_groups)
    _delete_items_in_collection(deployment_groups, exclude_persist=True)

    # delete services:
    services = client.services
    print 'deleting %d services' % len(services)
    _delete_items_in_collection(services)
    
    # delete decoys:
    decoys = client.decoys
    print 'deleting %d decoys' % len(decoys)
    _delete_items_in_collection(decoys)

if __name__ == '__main__':
    main()
