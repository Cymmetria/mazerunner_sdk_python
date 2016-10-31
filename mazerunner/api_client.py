import shutil
import requests
import requests_hawk

from mazerunner.ssl_adapter import SSLIgnoreHostnameAdapter
from mazerunner.exceptions import ValidationError, ServerError


class BaseCollection(object):
    """
    Base class of all collection classes
    """
    def __init__(self, api_client, obj_class):
        self._api_client = api_client
        self._obj_class = obj_class


class Collection(BaseCollection):
    """
    This is the base class of EditableCollection and AlertCollection. The following methods are
    applicable for the instances of the following classes: :class:`~AlertCollection`,
    :class:`~DecoyCollection`, :class:`~ServiceCollection`, :class:`~BreadcrumbCollection`
    and :class:`~DeploymentGroupCollection`
    """
    def __len__(self):
        query_params = self._get_query_params()
        response = self._api_client.api_request(self._get_url(), query_params=query_params)
        return response['count']

    def __iter__(self):
        for chunk in self.iter_chunks():
            for obj in chunk:
                yield obj

    def iter_chunks(self):
        """
        Load all the collection data, page by page, until done.
        """
        query_params = self._get_query_params()
        response = self._api_client.api_request(self._get_url(), query_params=query_params)
        results = response['results']
        while True:
            yield [self._obj_class(self._api_client, obj) for obj in results]
            # Get the next batch of objects if possible
            if response['next']:
                response = self._api_client.api_request(response['next'], query_params=query_params)
                results = response['results']
            else:
                return

    def _get_url(self):
        return self._api_client._api_urls[self._obj_class.NAME]

    def _get_query_params(self):
        return None

    def get_item(self, id):
        """
        Get a specific item by id

        :param id: Desired item id
        """
        response = self._api_client.api_request("{}{}/".format(self._get_url(), id))
        return self._obj_class(self._api_client, response)

    def params(self):
        """Request for the params of the collection"""
        response = self._api_client.api_request("{}{}/".format(self._get_url(), "params"))
        return response


class EditableCollection(Collection):
    """
    This is the base class of Collection which is the base class of :class:`~DecoyCollection`,
    :class:`~ServiceCollection`, :class:`~BreadcrumbCollection`
    and :class:`~DeploymentGroupCollection`. The following actions are applicable for their
    instances.
    """
    def create_item(self, data, files=None):
        """
        Create an instance of the element.

        It is recommended to prevent from using this method, and use the *create* methods of the
        relevant inheriting class instead.
        :param data: Element data
        :param files: Relevant files paths to upload for the element
        """
        response = self._api_client.api_request(self._get_url(), 'post', data=data, files=files)
        return self._obj_class(self._api_client, response)


class RelatedCollection(BaseCollection):
    """
    This describes a collection of associated elements
    """
    def __init__(self, api_client, obj_class, items):
        super(RelatedCollection, self).__init__(api_client, obj_class)

        self._items = items

    def __len__(self):
        return len(self._items)

    def __iter__(self):
        for item in self._items:
            yield self._obj_class(self._api_client, item)


class BaseEntity(object):
    """
    This is the base class of Alert and Entity.
    The methods below are applicable for: :class:`~Decoy`, :class:`~Service`, :class:`~Breadcrumb`,
    :class:`~DeploymentGroup` :class:`~Alert`
    """
    def __init__(self, api_client, param_dict):
        self._api_client = api_client
        self._param_dict = dict()
        self._update_entity_data(param_dict)
        self._update_related_collection_fields()

    def __repr__(self):
        properties = ' '.join('%s=%s' % (key, repr(value)) for key, value in self._param_dict.items())
        return '<%s: %s>' % (self.__class__.__name__, properties)

    def __getattribute__(self, attrname):
        try:
            return super(BaseEntity, self).__getattribute__(attrname)
        except AttributeError:
            self.load()
            return super(BaseEntity, self).__getattribute__(attrname)

    def _update_related_collection_fields(self):
        pass

    def _update_entity_data(self, data):
        self._param_dict.update(data)
        for key, value in data.items():
            setattr(self, key, value)

    def load(self):
        """
        Using the element id, populate all the element info from the server.
        """
        response = self._api_client.api_request(self.url)
        self._update_entity_data(response)
        self._update_related_collection_fields()


class Entity(BaseEntity):
    """
    This is the base class of :class:`~Decoy`, :class:`~Service`, :class:`~Breadcrumb`,
    and :class:`~DeploymentGroup`. The methods here are applicable for their instances.
    """
    def _update_item(self, data, files=None):
        response = self._api_client.api_request(self.url, 'put', data=data, files=files)
        self._update_entity_data(response)

    def _partial_update_item(self, data, files=None):
        non_empty_data = {key: value for key, value in data.iteritems() if value}
        if non_empty_data:
            response = self._api_client.api_request(self.url, 'patch', data=non_empty_data, files=files)
            self._update_entity_data(response)

    def delete(self):
        """Exterminate"""
        self._api_client.api_request(self.url, 'delete')


class DecoyCollection(EditableCollection):
    """
    A subset of decoys in the system.

    This entity will be returned by :func:`~mazerunner.api_client.APIClient.decoys`
    """
    def create(self, os, vm_type, name, hostname, chosen_static_ip=None, chosen_subnet=None, chosen_gateway=None,
               chosen_dns=None, chosen_interface=None, vlan=None, ec2_region=None, ec2_subnet_id=None, account=None):
        """
        Create a decoy

        Parameters:
            :param os: OS installed on the server. Options: \
            Ubuntu_1404/Windows_7/Windows_Server_2012/Windows_Server_2008
            :param vm_type: Server type. KVM or OVA
            :param name: Decoy name
            :param hostname: The server name as an attacker sees it when they login to the server.
            :param chosen_static_ip: A static ip for the server
            :param chosen_subnet: Subnet mask
            :param chosen_gateway: Default gateway address
            :param chosen_dns: The dns server address (This is NOT the name of the decoy)
            :param chosen_interface: The physical interface to which the decoy should be connected
            :param vlan: vlan to which the decoy will be connected (if applicable)
            :param ec2_region: EC2 region (e.g eu-west-1), if applicable.
            :param ec2_subnet_id: EC2 Subnet id, if applicable
            :param account: EC2 account id, if applicable
        """
        data = dict(
            os=os,
            vm_type=vm_type,
            name=name,
            hostname=hostname,
            chosen_static_ip=chosen_static_ip,
            chosen_subnet=chosen_subnet,
            chosen_gateway=chosen_gateway,
            chosen_dns=chosen_dns,
            chosen_interface=chosen_interface,
            vlan=vlan,
            ec2_region=ec2_region,
            ec2_subnet_id=ec2_subnet_id,
            account=account
        )
        non_empty_data = {key:value for key, value in data.iteritems() if value}
        return self.create_item(non_empty_data)


class Decoy(Entity):
    """
    A **decoy** is a virtual machine, to which you want to attract the attacker.

    A decoy may be a KVM machine nested inside the MazeRunner machine,
    or an external machine downloaded as an OVA and manually deployed on an ESX machine.
    """
    NAME = 'decoy'

    def update(self, name, chosen_static_ip=None, chosen_subnet=None, chosen_gateway=None, chosen_dns=None):
        """
        Change decoy configuration

        Parameters:
            :param name: Decoy name
            :param chosen_static_ip: Static ip to the decoy
            :param chosen_subnet: Decoy subnet mask
            :param chosen_gateway: Decoy default gateway (router address)
            :param chosen_dns: The DNS server the decoy will use. This is not a dns name of the
                decoy
        """
        data = dict(
            os=self.os,
            vm_type=self.vm_type,
            hostname=self.hostname,
            account=self.account,
            ec2_region=self.ec2_region,
            ec2_subnet_id=self.ec2_subnet_id,
            vlan=self.vlan,
            chosen_interface=self.chosen_interface,
            name=name,
            chosen_static_ip=chosen_static_ip,
            chosen_subnet=chosen_subnet,
            chosen_gateway=chosen_gateway,
            chosen_dns=chosen_dns
        )
        non_empty_data = {key: value for key, value in data.iteritems() if value}
        self._update_item(non_empty_data)

    def partial_update(self, name=None, chosen_static_ip=None, chosen_subnet=None, chosen_gateway=None, chosen_dns=None):
        """
        Change specific attributes of the decoy.

        Just like the :func:`~mazerunner.api_client.Decoy.update` method, but only the given
        attributes
        will update.

        name: Decoy name
        chosen_static_ip: Static ip to the decoy
        chosen_subnet: Decoy subnet mask
        chosen_gateway: Decoy default gateway (router address)
        chosen_dns: The DNS server the decoy will use. This is not a dns name of the decoy"""
        data = dict(
            name=name,
            chosen_static_ip=chosen_static_ip,
            chosen_subnet=chosen_subnet,
            chosen_gateway=chosen_gateway,
            chosen_dns=chosen_dns
        )
        self._partial_update_item(data)

    def power_on(self):
        """Start the decoy machine"""
        self._api_client.api_request("{}{}".format(self.url, 'power_on/'), 'post')

    def power_off(self):
        """Shutdown the decoy machine"""
        self._api_client.api_request("{}{}".format(self.url, 'power_off/'), 'post')

    def download(self, location_with_name):
        """Download the decoy OVA

        Parameters:
            :param location_with_name: Destination path
        """
        response = self._api_client.api_request("{}{}".format(self.url, 'download/'), stream=True)

        file_path = "{}.{}".format(location_with_name, "ova")
        with open(file_path, 'wb') as f:
            response.raw.decode_content = True
            shutil.copyfileobj(response.raw, f)


class ServiceCollection(EditableCollection):
    """
    A subset of services in the system.

    This entity will be returned by :func:`~mazerunner.api_client.APIClient.services`
    """
    def create(self, name, service_type, zip_file_path=None, **kwargs):
        """Create a service"""
        files = {"zip_file": open(zip_file_path, 'rb')} if zip_file_path else None
        data = dict(
            name=name,
            service_type=service_type
        )
        data.update(kwargs)
        return self.create_item(data, files=files)


class Service(Entity):
    """
    This is the application that will be install on the :class:`~Decoy`, to which the attacker will
    be tempted to connect.

    Examples for services:
        * Git
        * SSH
        * MySQL
        * Remote desktop
    """
    NAME = 'service'

    def _update_related_collection_fields(self):
        self.attached_decoys = RelatedCollection(self._api_client, Decoy, self._param_dict.get("attached_decoys", []))
        self.available_decoys = RelatedCollection(self._api_client, Decoy, self._param_dict.get("available_decoys", []))

    def update(self, name, zip_file_path=None, **kwargs):
        """Update all the service attributes"""
        files = {"zip_file": open(zip_file_path, 'rb')} if zip_file_path else None
        data = dict(
            name=name,
            service_type=self.service_type
        )
        data.update(kwargs)
        self._update_item(data, files=files)

    def partial_update(self, name=None, zip_file_path=None, **kwargs):
        """Update only the specified fields"""
        files = {"zip_file": open(zip_file_path, 'rb')} if zip_file_path else None
        data = dict(name=name)
        data.update(kwargs)
        self._partial_update_item(data, files=files)

    def connect_to_decoy(self, decoy_id):
        """
        Connect the service to the given decoy

        :param decoy_id: The id of the decoy to which the service should be attached
        """
        data = dict(decoy_id=decoy_id)
        self._api_client.api_request("{}{}".format(self.url, 'connect_to_decoy/'), 'post', data=data)
        self.load()

    def detach_from_decoy(self, decoy_id):
        """
        Detach the service from the given decoy

        :param decoy_id: Decoy id from which the service should be detached
        """
        data = dict(decoy_id=decoy_id)
        self._api_client.api_request("{}{}".format(self.url, 'detach_from_decoy/'), 'post', data=data)
        self.load()


class DeploymentGroupCollection(EditableCollection):
    """
    A subset of deployment groups in the system.

    This entity will be returned by :func:`~mazerunner.api_client.APIClient.deployment_groups`
    """
    def create(self, name, description=None):
        """
        Create a deployment group

        :param name: Deployment group name
        :param description: Deployment group description
        """
        data = dict(
            name=name,
            description=description
        )
        return self.create_item(data)


class DeploymentGroup(Entity):
    NAME = 'deployment-group'

    def update(self, name, description):
        """
        Update all the fields of the deployment group

        :param name: Deployment group name
        :param description: Deployment group description
        """
        data = dict(
            name=name,
            description=description
        )
        self._update_item(data)

    def partial_update(self, name=None, description=None):
        """
        Update only the specified fields

        :param name: Deployment group name
        :param description: Deployment group description
        """
        data = dict(
            name=name,
            description=description
        )
        self._partial_update_item(data)

    def check_conflicts(self, os):
        """
        Check whether this deployment group contains two or more conflicting breadcrumbs.

        A conflict will happen, for example, when two breadcrumbs of the same type use the
        same username

        :param os: OS type (Windows/Linux)
        """
        query_dict = dict(os=os)
        return self._api_client.api_request("{}{}".format(self.url, 'check_conflicts/'), query_params=query_dict)

    def deploy(self, location_with_name, os, download_type, download_format="ZIP"):
        """
        Download an installer of this deployment group

        :param location_with_name: Local destination path
        :param os: OS for which the installation is intended
        :param download_type: Installation action (install/uninstall)
        :param download_format: Installer format (ZIP/MSI/EXE)
        """
        query_dict = dict(os=os, download_type=download_type, download_format=download_format)
        response = self._api_client.api_request(
            "{}{}".format(self.url, 'deploy/'),
            query_params=query_dict, stream=True)

        file_path = "{}.{}".format(location_with_name, download_format.lower())
        with open(file_path, 'wb') as f:
            response.raw.decode_content = True
            shutil.copyfileobj(response.raw, f)


class BreadcrumbCollection(EditableCollection):
    """
    A subset of breadcrumbs in the system.

    This entity will be returned by :func:`~mazerunner.api_client.APIClient.breadcrumbs`
    """
    def create(self, name, breadcrumb_type, **kwargs):
        data = dict(
            name=name,
            breadcrumb_type=breadcrumb_type
        )
        data.update(kwargs)
        return self.create_item(data)


class Breadcrumb(Entity):
    """
    A breadcrumb is the connection info to a service on a decoy, and the way it's stored on the
    computer.

    In order to tempt the attacker to connect to our :class:`~Service` that is installed on our
    :class:`~Decoy`, we first need to create a key for connecting to it.

    Then, we'll take the key and deploy it to the organization endpoints, and wait
    for the attacker to find and use it.

    Therefore, the breadcrumb is comprised of two elements:
        - The keys using which the attacker will connect to the decoy
        - The way the breadcrumb will be put on the endpoint

    Examples for breadcrumbs:
        - A command of connection to mysql with user & password, stored in the history file of the
            endpoint
        - A user, password, and path of a network share, mounted on the endpoint
        - A cookie with a session token, stored in the browser on the endpoint
    """
    NAME = 'breadcrumb'

    def _update_related_collection_fields(self):
        self.attached_services = RelatedCollection(
            self._api_client, Decoy,
            self._param_dict.get("attached_services", []))
        self.available_services = RelatedCollection(
            self._api_client, Decoy,
            self._param_dict.get("available_services", []))
        self.deployment_groups = RelatedCollection(
            self._api_client, Decoy,
            self._param_dict.get("deployment_groups", []))

    def update(self, name, **kwargs):
        """Update breadcrumb configuration"""
        data = dict(
            name=name,
            breadcrumb_type=self.breadcrumb_type
        )
        data.update(kwargs)
        self._update_item(data)

    def partial_update(self, name=None, **kwargs):
        """Update specific fields in the breadcrumb. All unspecified fields will not be changed."""
        data = dict(name=name)
        data.update(kwargs)
        self._partial_update_item(data)

    def connect_to_service(self, service_id):
        """
        Connect breadcrumb to a service

        :param service_id: The service id to which the breadcrumb should be attached
        """
        data = dict(service_id=service_id)
        self._api_client.api_request("{}{}".format(self.url, 'connect_to_service/'), 'post', data=data)
        self.load()

    def detach_from_service(self, service_id):
        """
        Detach the breadcrumb from the given service
        :param service_id: Service id from which the breadcrumbs whould be detached
        """
        data = dict(service_id=service_id)
        self._api_client.api_request("{}{}".format(self.url, 'detach_from_service/'), 'post', data=data)
        self.load()

    def deploy(self, location_with_name, os, download_type, download_format="ZIP"):
        """
        Generate a breadcrumb and download it

        :param location_with_name: Local destination path for the breadcrumb
        :param os: OS to which the breadcrumb installation is targeted (Windows/Linux)
        :param download_type: Installation action (install/uninstall)
        :param download_format: Installer format (ZIP/EXE/MSI)
        """
        query_dict = dict(os=os, download_type=download_type, download_format=download_format)
        response = self._api_client.api_request(
            "{}{}".format(self.url, 'deploy/'),
            query_params=query_dict, stream=True)

        file_path = "{}.{}".format(location_with_name, download_format.lower())
        with open(file_path, 'wb') as f:
            response.raw.decode_content = True
            shutil.copyfileobj(response.raw, f)

    def add_to_group(self, deployment_group_id):
        """
        Add the breadcrumb to the given deployment group

        :param deployment_group_id: Deployment group id to which the breadcrumb should be added
        """
        data = dict(deployment_group_id=deployment_group_id)
        self._api_client.api_request("{}{}".format(self.url, 'add_to_group/'), 'post', data=data)
        self.load()

    def remove_from_group(self, deployment_group_id):
        """
        Remove the breadcrumb from the given deployment group

        :param deployment_group_id: Deployment group id from which the breadcrumb should be removed
        """
        data = dict(deployment_group_id=deployment_group_id)
        self._api_client.api_request("{}{}".format(self.url, 'remove_from_group/'), 'post', data=data)
        self.load()


class AlertCollection(Collection):
    """
    A subset of the alerts in the system

    This entity will be returned by :func:`~mazerunner.api_client.APIClient.alerts`
    """
    def __init__(self, api_client, obj_class, filter_enabled=False, only_alerts=False, alert_types=None):
        super(AlertCollection, self).__init__(api_client, obj_class)
        self.filter_enabled = filter_enabled
        self.only_alerts = only_alerts
        self.alert_types = alert_types

    def _get_query_params(self):
        return dict(filter_enabled=self.filter_enabled,
                    only_alerts=self.only_alerts,
                    alert_types=self.alert_types)

    def filter(self, filter_enabled=False, only_alerts=False, alert_types=None):
        """
        Get alerts by query

        :param filter_enabled: When False, the only_alerts and alert_types params will be ignored.
        :param only_alerts: Take only alerts in 'Alert' status (and exclude the 'mute' and 'ignore')
        :param alert_types: A list of alert types
        :return: A filtered AlertCollection
        """
        formatted_alert_types = " ".join(alert_types) if alert_types else ""
        return AlertCollection(self._api_client, Alert, filter_enabled=filter_enabled, only_alerts=only_alerts,
                               alert_types=formatted_alert_types)

    def export(self, location_with_name):
        """
        Export all alerts to CSV

        :param location_with_name: Download destination file
        """
        query_params = self._get_query_params()
        response = self._api_client.api_request("{}{}".format(self._get_url(), 'export/'), stream=True,
                                                query_params=query_params)

        file_path = "{}.csv".format(location_with_name)
        with open(file_path, 'wb') as f:
            response.raw.decode_content = True
            shutil.copyfileobj(response.raw, f)

    def delete(self, selected_alert_ids=None, delete_all_filtered=False):
        """
        Delete alerts by ids list

        Parameters:
            :param selected_alert_ids: List of alerts to be deleted
            :param delete_all_filtered: Delete alerts by query, rather than by ids list. See \
            example below

        Example 1: Delete alerts by id::

            client = mazerunner.connect(...)
            all_alerts = client.alerts.filter()
            all_alerts.delete([101,102,103])

        Example 2: Delete alerts by filter::

            client = mazerunner.connect(...)
            filtered_alerts = client.alerts.filter(alert_types=['share', 'http'])
            filtered_alerts.delete(delete_all_filtered=True)
        """
        data = dict(selected_alert_ids=selected_alert_ids,
                    delete_all_filtered=delete_all_filtered)
        query_params = self._get_query_params()
        self._api_client.api_request("{}{}".format(self._get_url(), 'delete_selected/'), 'post', data=data,
                                     query_params=query_params)


class Alert(BaseEntity):
    """
    An alert is automatically generated by the system every time an attacker interacts with the
    decoy.

    The alert contains the information of a detected attack: what code was executed,
    what query was run on the DB, what SMB shares were accessed, etc.
    """
    NAME = 'alert'

    def delete(self):
        """Delete the alert"""
        self._api_client.api_request(self.url, 'delete')

    def download_image_file(self, location_with_name):
        """
        Download image file of the executed code

        :param location_with_name: Download destination path
        """
        response = self._api_client.api_request("{}{}".format(self.url, 'download_image_file/'), stream=True)

        file_path = "{}.bin".format(location_with_name)
        with open(file_path, 'wb') as f:
            response.raw.decode_content = True
            shutil.copyfileobj(response.raw, f)

    def download_memory_dump_file(self, location_with_name):
        """
        Download memory dump of the executed code

        :param location_with_name: Download destination path
        """
        response = self._api_client.api_request("{}{}".format(self.url, 'download_memory_dump_file/'), stream=True)

        file_path = "{}.bin".format(location_with_name)
        with open(file_path, 'wb') as f:
            response.raw.decode_content = True
            shutil.copyfileobj(response.raw, f)

    def download_network_capture_file(self, location_with_name):
        """
        Download alert info in pcap format

        :param location_with_name: Download destination path
        """
        response = self._api_client.api_request("{}{}".format(self.url, 'download_network_capture_file/'), stream=True)

        file_path = "{}.pcap".format(location_with_name)
        with open(file_path, 'wb') as f:
            response.raw.decode_content = True
            shutil.copyfileobj(response.raw, f)

    def download_stix_file(self, location_with_name):
        """
        Download alert info in stix format

        :param location_with_name: Download destination path
        """
        response = self._api_client.api_request("{}{}".format(self.url, 'download_stix_file/'), stream=True)

        file_path = "{}.xml".format(location_with_name)
        with open(file_path, 'wb') as f:
            response.raw.decode_content = True
            shutil.copyfileobj(response.raw, f)


class APIClient(object):
    """
    This is the starting point for any interaction with MazeRunner

    Parameters:
        :param host: The hostname or ip address of MazeRunner
        :param api_key: Api key ID. See below how to get one.
        :param api_secret: Secret key. See below how to get one.
        :param certificate: Path to certificate file. See below how to get one.
        :param use_http: Use unsecure http connection (instead of secure https)

    How to get your api key:

        - Login to MazeRunner in your browser
        - Click on the gear on the top right corner and select Manage API Keys
        - Click create api key
        - Select a description and press Create
        - The api_key will appear as "Key ID"
        - The api_secret will appear as "Secret Key"

    How to get your certificate:

        - Login to MazeRunner in your browser
        - Click on the gear on the top right corner and select Manage API Keys
        - Click download SSL certificate


    Example::

            client = mazerunner.connect(ip_address='1.2.3.4',
                                           api_key='my-api-key',
                                           api_secret='my-api-secret',
                                           certificate='/path/to/MazeRunner.crt')

            my_service = client.services.get_item(id=8)
    """
    def __init__(self, host, api_key, api_secret, certificate, use_http=False):
        '''
            certificate - path to SSL certificate of the server. If False or None, SSL verification is skipped.
        '''
        schema = 'https'
        if use_http:
            schema = 'http'
        self._auth = requests_hawk.HawkAuth(id=api_key, key=api_secret, algorithm="sha256")
        if certificate is None:
            self._certificate = False
        else:
            self._certificate = certificate
        self._base_url = '%(schema)s://%(host)s' % dict(schema=schema, host=host)
        self._session = requests.Session()
        if not use_http:
            self._session.mount(self._base_url, SSLIgnoreHostnameAdapter())
        self._api_urls = self.api_request('/api/v1.0/')

    def api_request(self,
                    url,
                    method='get',
                    query_params=None,
                    data=None,
                    files=None,
                    stream=False):
        """
        Execute a synchronic api request against MazeRunner and return the result

        Parameters:

                :param url: The request url
                :param method: HTTP method (get, post, put, patch, delete)
                :param query_params: A dictionary of of the request query parameters
                :param data: Request body
                :param files: Files to be sent with the request
                :param stream: Use stream
                :return: Request result

            **Note:** You'll find out that what you were trying to do is already implemented
            with a built-in method. You better use it instead.
        """
        if not url.startswith("http"):
            url = self._base_url + url

        request_args = dict(
            method=method,
            url=url,
            params=query_params,
            auth=self._auth
        )
        if not files:
            request_args['json'] = data
        else:
            request_args['data'] = data
            request_args['files'] = files

        req = requests.Request(**request_args)
        resp = self._session.send(req.prepare(), verify=self._certificate, stream=stream)

        if str(resp.status_code).startswith("4"):
            raise ValidationError(resp.status_code, resp.content)
        if str(resp.status_code).startswith("5"):
            raise ServerError(resp.status_code, resp.content)

        # If stream, return the response as is
        if stream:
            return resp

        if method == "delete":
            return

        content_type = resp.headers.get("Content-Type", None)
        if content_type != "application/json":
            raise ValidationError(
                resp.status_code,
                "Bad response content type: {content_type}\nContent:\n{content}".format(
                    content_type=content_type,
                    content=resp.content)
            )
        try:
            return resp.json()
        except ValueError:
            raise ValidationError(
                resp.status_code,
                "Bad response: Not json.\nContent:\n{content}".format(content=resp.content)
            )

    @property
    def decoys(self):
        """
        Get a :func:`~mazerunner.api_client.DecoyCollection` instance, on which you can
        perform CRUD operations

        Example::

            client = mazerunner.connect(...)
            backup_server_story_decoy = client.decoys.create(
                name='backup_server_decoy',
                os='Windows_Server_2012',
                hostname: 'backup_server',
                vm_type: "KVM")

            old_decoy = client.decoys.get_item(id=5)
            old_decoy.delete()
        """
        return DecoyCollection(self, Decoy)

    @property
    def services(self):
        """
        Get a :func:`~mazerunner.api_client.ServiceCollection` instance, on which you can
        perform CRUD operations

        Example::

            client = mazerunner.connect(...)
            app_db_service = client.services.create(
                name='app_db_service',
                type='mysql')
        """
        return ServiceCollection(self, Service)

    @property
    def deployment_groups(self):
        """
        Get a :func:`~mazerunner.api_client.DeploymentGroupCollection` instance, on which you can
        perform CRUD operations

        Example::

            client = mazerunner.connect(...)
            hr_deployment_group = client.deployment_groups.create(name='breadcrumbs_for_hr_machines')
        """
        return DeploymentGroupCollection(self, DeploymentGroup)

    @property
    def breadcrumbs(self):
        """
        Get a :class:`~mazerunner.api_client.BreadcrumbCollection` instance, on which you can
        perform CRUD operations


        Example::

            client = mazerunner.connect(...)
            mysql_breadcrumb = client.breadcrumbs.create(
                breadcrumb_type='mysql',
                name='mysql_breadcrumb',
                deploy_for='root',
                installation_type='mysql_history')
            """
        return BreadcrumbCollection(self, Breadcrumb)

    @property
    def alerts(self):
        """
        Get a :func:`~mazerunner.api_client.AlertCollection` instance, on which you can
        perform CRUD operations:

        Example::

            client = mazerunner.connect(...)
            code_alerts = client.alerts.filter(alert_types=['code'])
        """
        return AlertCollection(self, Alert)
