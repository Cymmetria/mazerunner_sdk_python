#!/usr/bin/env python2

import argparse
from socket import gethostbyaddr
from netaddr import IPNetwork
import mazerunner


def get_hostname_for_ip(ip_address):
    name = None
    try:
        name, alias, addresslist = gethostbyaddr(ip_address)
    except Exception:
        pass
    return name


def find_deployment_group(client, group_name):
    for group in client.deployment_groups:
        if group.name == group_name:
            return group

    raise ValueError('Deployment group "{}" could not be found'.format(group_name))


def find_endpoint(endpoints, hostname):
    hostname = hostname.lower()
    for x in endpoints:
        if (x.dns and x.dns.lower() == hostname) or \
           (x.hostname and x.hostname.lower() == hostname):
            return x
    return None


def assign_group_to_cidr(deployment_group, cidr, connection_params):
    network = IPNetwork(cidr)

    client = mazerunner.connect(**connection_params)
    group = find_deployment_group(client, deployment_group)

    for address in network.iter_hosts():
        name = get_hostname_for_ip(str(address))
        if not name:
            print "Could not resolve hostname for {}".format(address)
            continue
        # Find the endpoint object
        endpoints = client.endpoints.filter(name)
        e = find_endpoint(endpoints, name)
        if not e:
            print "Could not find endpoint object for {}".format(name)
            continue
        try:
            client.endpoints.reassign_to_group(group, [e])
        except mazerunner.exceptions.ValidationError:
            # Workaround...
            pass

        print "Endpoint at {} ({}) assigned to group {}".format(address, name, deployment_group)


def main():
    parser = argparse.ArgumentParser("Assign deployment group to all endpoints in a CIDR range")
    parser.add_argument('mazerunner', help="IP address of MazeRunner management server")
    parser.add_argument('api_key', help="API key")
    parser.add_argument('api_secret', help="API secert key")
    parser.add_argument('certificate', help="Path to MazeRunner's SSL certificate")
    parser.add_argument('deployment_group', help="Name of the deployment group to assign to")
    parser.add_argument('cidr', help='CIDR range to assign (e.g. 192.168.0.0/24)')

    args = parser.parse_args()

    connection_params = dict(ip_address=args.mazerunner,
                             api_key=args.api_key,
                             api_secret=args.api_secret,
                             certificate=args.certificate)
    assign_group_to_cidr(args.deployment_group, args.cidr, connection_params)


if __name__ == '__main__':
    main()
