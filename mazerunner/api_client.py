import json
import urlparse
from httplib import NO_CONTENT
import shutil
from numbers import Number

import requests
import requests_hawk
from mazerunner.exceptions import ValidationError, ServerError, BadParamError, \
    InvalidInstallMethodError

ENTRIES_PER_PAGE = 500
ISO_TIME_FORMAT = "%Y-%m-%d"


class BaseCollection(object):
    MODEL_CLASS = None

    def __init__(self, api_client, obj_class=None):
        """
        :param api_client: The connection instance.
        :param obj_class: The class, instance of which all the members should be.
        """
        self._api_client = api_client
        self._obj_class = obj_class or self.MODEL_CLASS


class Collection(BaseCollection):
    def __len__(self):
        query_params = self._get_query_params()
        response = self._api_client.api_request(self._get_url(), query_params=query_params)
        return response["count"]

    def __iter__(self):
        for chunk in self._iter_chunks():
            for obj in chunk:
                yield obj

    def _iter_chunks(self):
        query_params = self._get_query_params()
        response = self._api_client.api_request(self._get_url(), query_params=query_params)
        results = response["results"]
        while True:
            yield [self._obj_class(self._api_client, obj) for obj in results]

            # Get the next batch of objects if possible
            if response.get("next"):
                response = self._api_client.api_request(response["next"], query_params=query_params)
                results = response["results"]
            else:
                return

    def _get_url(self):
        return self._api_client.api_urls[self._obj_class.NAME]

    def _get_query_params(self):
        return None

    def get_item(self, id):
        """
        Get a specific item by ID.

        :param id: Desired item ID.
        """
        query_params = self._get_query_params()
        response = self._api_client.api_request(url="{}{}/".format(self._get_url(), id),
                                                query_params=query_params)
        return self._obj_class(self._api_client, response)

    def params(self):
        """
        Request for information about the applicable values for the entity fields.
        """
        response = self._api_client.api_request("{}{}/".format(self._get_url(), "params"))
        return response


class EditableCollection(Collection):
    def create_item(self, data, files=None):
        """
        Create an instance of the element.

        It is recommended to avoid using this method. Instead, use the *create* methods of the
        relevant inheriting class.

        :param data: Element data.
        :param files: Relevant file paths to upload for the element.
        """
        response = self._api_client.api_request(self._get_url(), "post", data=data, files=files)
        return self._obj_class(self._api_client, response).load()


class UnpaginatedEditableCollection(EditableCollection):
    def __len__(self):
        query_params = self._get_query_params()
        response = self._api_client.api_request(self._get_url(), query_params=query_params)
        return len(response)

    def __iter__(self):
        query_params = self._get_query_params()
        response = self._api_client.api_request(self._get_url(), query_params=query_params)
        for item_data in response:
            yield self._obj_class(self._api_client, item_data)


class RelatedCollection(BaseCollection):
    def __init__(self, api_client, obj_class, items):
        """
        :param api_client: The connection instance.
        :param obj_class: The class, instance of which all the members should be.
        :param items: A list of raw dicts containing the data of the members.
        """
        super(RelatedCollection, self).__init__(api_client, obj_class)
        self._items = items

    def __len__(self):
        return len(self._items)

    def __iter__(self):
        for item in self._items:
            yield self._obj_class(self._api_client, item)


class BaseEntity(object):
    RELATED_COLLECTIONS = {}
    RELATED_FIELDS = {}

    def __init__(self, api_client, param_dict):
        """
        :param api_client: The connection instance.
        :param param_dict: A dict of the instance details.
        """
        self._api_client = api_client
        self._param_dict = dict()
        self._update_entity_data(param_dict)
        self._update_related_fields()

    def __repr__(self):
        properties = " ".join("%s=%s" % (key, repr(value))
                              for key, value
                              in self._param_dict.items())
        return "<%s: %s>" % (self.__class__.__name__, properties)

    def _update_related_fields(self):
        for key, field_type in self.RELATED_COLLECTIONS.iteritems():
            setattr(self, key, RelatedCollection(self._api_client,
                                                 field_type,
                                                 self._param_dict.get(key, [])))

        for key, field_type in self.RELATED_FIELDS.iteritems():
            value = self._param_dict.get(key, None)
            if value:
                setattr(self, key, field_type(self._api_client, value))

    def __getattr__(self, item):
        if item not in self._param_dict:
            self.load()

        if item not in self._param_dict:
            raise AttributeError("'%s' object has no attribute '%s'" % (self.__class__.__name__,
                                                                        item))

        return self._param_dict[item]

    def _update_entity_data(self, data):
        self._param_dict.update(data)

    def load(self):
        """
        Using the element ID, populate all of the element info from the server.
        """
        response = self._api_client.api_request(self.url)
        self._update_entity_data(response)
        self._update_related_fields()
        return self


class Entity(BaseEntity):
    def _update_item(self, data, files=None):
        response = self._api_client.api_request(self.url, "put", data=data, files=files)
        self._update_entity_data(response)

    def _partial_update_item(self, data, files=None):
        non_empty_data = {key: value for key, value in data.iteritems() if value}
        if non_empty_data:
            response = self._api_client.api_request(url=self.url,
                                                    method="patch",
                                                    data=non_empty_data,
                                                    files=files)
            self._update_entity_data(response)

    def delete(self):
        """
        Delete this element.
        """
        self._api_client.api_request(self.url, "delete")


class Decoy(Entity):
    """
    A **decoy** is a virtual machine, to which you want to attract the attacker.

    A decoy may be a KVM machine nested inside the MazeRunner machine,
    or an external machine downloaded as an OVA and manually deployed on an ESX machine.
    """

    NAME = "decoy"

    def update(self, name, chosen_static_ip=None, chosen_subnet=None, chosen_gateway=None,
               chosen_dns=None, dns_address=""):
        """
        Change decoy configuration.

        :param name: Decoy name.
        :param chosen_static_ip: Static IP of the decoy.
        :param chosen_subnet: Decoy subnet mask.
        :param chosen_gateway: Decoy default gateway (router address).
        :param chosen_dns: The DNS server the decoy will use. This is not a DNS name of the \
            decoy.
        :param dns_address: The DNS name of the decoy. If set, the breadcrumbs will use
            this DNS instead of the decoy IP.
        """
        data = dict(
            os=self.os,
            vm_type=self.vm_type,
            hostname=self.hostname,
            account=self.account,
            ec2_region=self.ec2_region,
            ec2_subnet_id=self.ec2_subnet_id,
            vlan=self.vlan,
            interface=self.interface,
            name=name,
            chosen_static_ip=chosen_static_ip,
            chosen_subnet=chosen_subnet,
            chosen_gateway=chosen_gateway,
            chosen_dns=chosen_dns,
            dns_address=dns_address,
            network_type=self.network_type
        )
        non_empty_data = {key: value for key, value in data.iteritems() if value}
        self._update_item(non_empty_data)

    def power_on(self):
        """
        Start the decoy machine.
        """
        self._api_client.api_request("{}{}".format(self.url, "power_on/"), "post")

    def recreate(self):
        """
        Recreate the decoy machine.
        """
        self._api_client.api_request("{}{}".format(self.url, "recreate/"), "post")

    def power_off(self):
        """
        Shut down the decoy machine.
        """
        self._api_client.api_request("{}{}".format(self.url, "power_off/"), "post")

    def test_dns(self):
        """
        Check whether the decoy is properly registered in the DNS server.
        """
        try:
            return self._api_client.api_request("{}{}".format(self.url, "test_dns/"), "post")
        except ValidationError as e:
            data = json.loads(e.message)
            errors = data.get("non_field_errors", [])
            if len(errors) == 1 and errors[0].startswith("Failed to resolve address for decoy"):
                return False
            raise

    def download(self, location_with_name):
        """
        Download the decoy. Applicable for OVA only.

        :param location_with_name: Destination path.
        """
        self._api_client.request_and_download(url="{}{}".format(self.url, "download/"),
                                              destination_path="{}.{}".format(location_with_name, "ova"))


class DecoyCollection(EditableCollection):
    """
    A subset of decoys in the system.

    This entity will be returned by :py:attr:`api_client.APIClient.decoys`.
    """

    MODEL_CLASS = Decoy

    def create(self, os, vm_type, name, hostname, chosen_static_ip=None, chosen_subnet=None,
               chosen_gateway=None, chosen_dns=None, interface=1, vlan=None,
               ec2_region=None, ec2_subnet_id=None, account=None, dns_address="", network_type="PROMISC"):
        """
        Create a decoy.

        :param network_type: Network type of the decoy. Options : \
        PROMISC, NON_PROMISC, VLAN_TRUNK
        :param os: OS installed on the server. Options: \
        Ubuntu_1404, Windows_7, Windows_Server_2012, Windows_Server_2008.
        :param vm_type: Server type. KVM for nested (recommended) or OVA for standalone.
        :param name: Internal name of the decoy.
        :param hostname: The decoy server name as an attacker sees it when they log in to \
        the server.
        :param chosen_static_ip: A static IP for the server.
        :param chosen_subnet: Decoy subnet mask.
        :param chosen_gateway: Decoy default gateway address.
        :param chosen_dns: The DNS server address (This is NOT the name of the decoy).
        :param interface: The physical interface to which the decoy should be connected. \
        :param vlan: VLAN to which the decoy will be connected (if applicable).
        :param ec2_region: EC2 region (e.g., eu-west-1), if applicable.
        :param ec2_subnet_id: EC2 subnet ID, if applicable.
        :param account: EC2 account ID, if applicable.
        :param dns_address: The DNS name of the decoy. If given, the breadcrumbs will use this \
        DNS name instead of the decoy IP.
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
            interface=interface,
            vlan=vlan,
            ec2_region=ec2_region,
            ec2_subnet_id=ec2_subnet_id,
            account=account,
            dns_address=dns_address,
            network_type=network_type
        )
        non_empty_data = {key: value for key, value in data.iteritems() if value}
        return self.create_item(non_empty_data)


class Service(Entity):
    """
    This is the application that will be installed on the :class:`api_client.Decoy`, \
    to which the attacker will be tempted to connect.

    Examples of services:

        * Git
        * SSH
        * MySQL
        * Remote desktop
    """

    NAME = "service"

    RELATED_COLLECTIONS = {
        "attached_decoys": Decoy,
        "available_decoys": Decoy
    }

    def update(self, name, zip_file_path=None, **kwargs):
        """
        Update all of the service attributes.

        :param name: Internal name for the service.
        :param zip_file_path: A file to upload, if applicable.
        :param kwargs: Additional relevant parameters.
        """
        files = {"zip_file": open(zip_file_path, "rb")} if zip_file_path else None
        data = dict(
            name=name,
            service_type=self.service_type
        )
        data.update(kwargs)
        self._update_item(data, files=files)

    def connect_to_decoy(self, decoy_id):
        """
        Connect the service to the given decoy.

        :param decoy_id: The ID of the decoy to which the service should be attached.
        """
        data = dict(decoy_id=decoy_id)
        self._api_client.api_request(url="{}{}".format(self.url, "connect_to_decoy/"),
                                     method="post",
                                     data=data)
        self.load()

    def detach_from_decoy(self, decoy_id):
        """
        Detach the service from the given decoy.

        :param decoy_id: Decoy ID from which the service should be detached.
        """
        data = dict(decoy_id=decoy_id)
        self._api_client.api_request(url="{}{}".format(self.url, "detach_from_decoy/"),
                                     method="post",
                                     data=data)
        self.load()


class ServiceCollection(EditableCollection):
    """
    A subset of services in the system.

    This entity will be returned by :py:attr:`api_client.APIClient.services`.
    """

    MODEL_CLASS = Service

    def create(self, name, service_type, zip_file_path=None, **kwargs):
        """
        Create a service.

        :param name: An internal name for the service.
        :param service_type: The application you want to install. Try the params method for the \
        available options.
        :param zip_file_path: The path of a ZIP file to upload, if applicable.
        :param kwargs: Additional relevant parameters.
        """
        files = {"zip_file": open(zip_file_path, "rb")} if zip_file_path else None
        data = dict(
            name=name,
            service_type=service_type
        )
        data.update(kwargs)
        return self.create_item(data, files=files)


class DeploymentGroup(Entity):
    """
    A **deployment group** is a connection between a list of \
    :class:`breadcrumbs <api_client.Breadcrumb>` \
    and a list of
    :class:`endpoints <api_client.Endpoint>` on which the breadcrumbs should be deployed.

    The relationship between a breadcrumb and a deployment group is many-to-many. \n
    The relationship between an endpoint to a deployment group is many-to-one.

    When set, you can use :py:meth:`api_client.DeploymentGroup.auto_deploy` to install \
    the deployment group's associated breadcrumbs on the deployment group's associated endpoints.
    """

    NAME = "deployment-group"

    def update(self, name, description):
        """
        Update all of the deployment group's fields.

        :param name: Deployment group name.
        :param description: Deployment group description.
        """
        data = dict(
            name=name,
            description=description
        )
        self._update_item(data)

    def partial_update(self, name=None, description=None):
        """
        Update only the specified fields.

        :param name: Deployment group name.
        :param description: Deployment group description.
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
        same username.

        :param os: OS type (Windows/Linux).
        """
        query_dict = dict(os=os)
        return self._api_client.api_request(url="{}{}".format(self.url, "check_conflicts/"),
                                            query_params=query_dict)

    def deploy(self, location_with_name, os, download_type, download_format="ZIP"):
        """
        Download this deployment group's installer/uninstaller.

        :param location_with_name: Local destination path.
        :param os: OS for which the installation is intended.
        :param download_type: Installation action (install/uninstall).
        :param download_format: Installer format (ZIP/MSI/EXE).
        """
        query_dict = dict(os=os, download_type=download_type, download_format=download_format)
        file_path = "{}.{}".format(location_with_name, download_format.lower())
        self._api_client.request_and_download(url="{}{}".format(self.url, "deploy/"),
                                              destination_path=file_path,
                                              query_params=query_dict)

    def auto_deploy(self, install_method, run_method, username, password, domain="",
                    deploy_on="all"):
        """
        Deploy all the breadcrumbs that are members of this deployment group on all the endpoints
        that are assigned to this deployment group.

        :param install_method: The format of the installation file: EXE_DEPLOY or CMD_DEPLOY.
        :param run_method: Currently only PS_EXEC is supported.
        :param username: A Windows username, which MazeRunner will use to authenticate itself for \
        installing on the endpoint.
        :param password: The password for that user.
        :param domain: The domain of that user. Pass an empty string for a local user.
        :param deploy_on: Options are: "all" for all endpoints assigned to this group, \
        or "failed" if you only want to deploy on the endpoints where no previous successful \
        deployment has taken place.
        """
        data = dict(
            username=username,
            password=password,
            install_method=install_method,
            run_method=run_method,
            domain=domain,
            deploy_on=deploy_on
        )
        self._api_client.api_request("{}{}".format(self.url, "auto_deploy/"), "post", data=data)


class DeploymentGroupCollection(EditableCollection):
    """
    A subset of deployment groups in the system.

    This entity will be returned by :py:attr:`api_client.APIClient.deployment_groups`.
    """

    MODEL_CLASS = DeploymentGroup
    ALL_BREADCRUMBS_DEPLOYMENT_GROUP_ID = 1

    def create(self, name, description=None):
        """
        Create a deployment group.

        :param name: Deployment group name.
        :param description: Deployment group description.
        """
        data = dict(
            name=name,
            description=description
        )
        return self.create_item(data)

    def test_deployment_credentials(self, addr, install_method, username, password, domain=None):
        """
        Check your credentials on a specific endpoint, without actually installing anything on it.
        Useful before performing a large-scale deployment using the auto_deploy or
        auto_deploy_groups.

        :param addr: The IP of the tested endpoint.
        :param install_method: Use here the same install_method you're planning to use in \
        auto_deploy or auto_deploy_groups.
        :param username: The Windows user you want MazeRunner to use when connecting to the endpoint.
        :param password: The password of that user.
        :param domain: The domain of that user. Leave as an empty string for local user.
        :return: Test results dict consisting of a "success" key. In case of failure, \
        a "reason" key will appear as well.
        """
        data = dict(
            username=username,
            password=password,
            addr=addr,
            install_method=install_method,
            domain=domain
        )
        return self._api_client.api_request(url="{}{}".format(self._get_url(),
                                                              "test_deployment_credentials/"),
                                            method="post", data=data)

    def auto_deploy_groups(self, deployment_groups_ids, install_method, run_method,
                           username, password, domain=None, deploy_on="all"):
        """
        For each of the specified deployment_groups_ids, deploy all its member breadcrumbs on all
        the endpoints associated with it.

        :param deployment_groups_ids: A list of the desired deployment group IDs.
        :param install_method: The format of the installation file: EXE_DEPLOY or CMD_DEPLOY.
        :param run_method: Currently, only PS_EXEC is supported.
        :param username: A Windows username, which MazeRunner will use to authenticate itself for \
        installing on the endpoint.
        :param password: The password for that user.
        :param domain: The domain of that user. Pass an empty string for a local user.
        :param deploy_on: Options are: "all" for all endpoints assigned to this group, \
        or "failed" if you only want to deploy on the endpoints where no previous successful \
        deployment has taken place.
        """
        data = dict(
            username=username,
            password=password,
            deployment_groups_ids=deployment_groups_ids,
            install_method=install_method,
            run_method=run_method,
            domain=domain,
            deploy_on=deploy_on
        )
        url = "{}{}/".format(self._get_url(), "deploy")
        return self._api_client.api_request(url=url,
                                            method="post",
                                            data=data)

    def deploy_all(self, location_with_name, os, download_format="ZIP"):
        """
        Download this deployment group's installers & uninstallers.

        :param location_with_name: Local destination path.
        :param os: OS for which the installation is intended.
        :param download_format: Installer format (ZIP/MSI/EXE).
        """
        file_path = "{}.{}".format(location_with_name, download_format.lower())
        self._api_client.request_and_download(url="{}{}".format(self._get_url(), "deploy_all/"),
                                              destination_path=file_path,
                                              query_params=dict(os=os, download_format=download_format))

    def params(self):
        raise NotImplementedError


class Breadcrumb(Entity):
    """
    A breadcrumb consists of connection credentials deployed on an endpoint. An attacker will find
    and use these credentials to connect to a service on a decoy.

    In order to tempt the attacker to connect to our :class:`api_client.Service` that \
     is installed on our :class:`api_client.Decoy`, we first need to create a key \
     for connecting to it.

    Then, we will take the key and deploy it to the organization's endpoints, and wait
    for the attacker to find and use it.

    Therefore, the breadcrumb is comprised of two elements:

        - The keys the attacker will use to connect to the decoy.
        - Where the breadcrumb will be deployed to on the endpoint.

    Examples of breadcrumbs:

        - A command for connecting to MySQL with user & password, stored in the endpoint's history file.
        - A user, password, and path of a network share, mounted on the endpoint.
        - A cookie with a session token, stored in the endpoint's browser.
    """

    NAME = "breadcrumb"

    RELATED_COLLECTIONS = {
        "attached_services": Service,
        "available_services": Service,
        "deployment_groups": DeploymentGroup
    }

    def update(self, name, **kwargs):
        """
        Update breadcrumb configuration.

        :param name: An internal name for the breadcrumb.
        :param kwargs: Additional parameters for that breadcrumb. See the params method for \
        information about the options.
        """
        data = dict(
            name=name,
            breadcrumb_type=self.breadcrumb_type
        )
        data.update(kwargs)
        self._update_item(data)

    def connect_to_service(self, service_id):
        """
        Connect the breadcrumb to a service.

        :param service_id: The service ID to which the breadcrumb should be attached.
        """
        data = dict(service_id=service_id)
        self._api_client.api_request(url="{}{}".format(self.url, "connect_to_service/"),
                                     method="post",
                                     data=data)
        self.load()

    def detach_from_service(self, service_id):
        """
        Detach the breadcrumb from a service.

        :param service_id: Service ID from which the breadcrumbs should be detached.
        """
        data = dict(service_id=service_id)
        self._api_client.api_request(url="{}{}".format(self.url, "detach_from_service/"),
                                     method="post",
                                     data=data)
        self.load()

    def deploy(self, location_with_name, os, download_type, download_format="ZIP"):
        """
        Generate a breadcrumb and download it.

        :param location_with_name: Local destination path for the breadcrumb.
        :param os: OS to which the breadcrumb installation is targeted (Windows/Linux).
        :param download_type: Installation action (install/uninstall).
        :param download_format: Installer format (ZIP/EXE/MSI).
        """
        query_dict = dict(os=os, download_type=download_type, download_format=download_format)
        file_path = "{}.{}".format(location_with_name, download_format.lower())
        self._api_client.request_and_download(url="{}{}".format(self.url, "deploy/"),
                                              destination_path=file_path,
                                              query_params=query_dict)

    def add_to_group(self, deployment_group_id):
        """
        Add the breadcrumb to the given deployment group.

        :param deployment_group_id: Deployment group ID to which the breadcrumb should be added.
        """

        if not isinstance(deployment_group_id, Number):
            raise BadParamError("deployment_group_id must be a number")

        data = dict(deployment_group_id=deployment_group_id)
        self._api_client.api_request("{}{}".format(self.url, "add_to_group/"), "post", data=data)
        self.load()

    def remove_from_group(self, deployment_group_id):
        """
        Remove the breadcrumb from the given deployment group.

        :param deployment_group_id: Deployment group ID from which the breadcrumb should be removed.
        """
        data = dict(deployment_group_id=deployment_group_id)
        self._api_client.api_request(url="{}{}".format(self.url, "remove_from_group/"),
                                     method="post",
                                     data=data)
        self.load()

    def download_breadcrumb_honeydoc(self, location_with_name):
        """
        Download the HoneyDoc file for this breadcrumb (for HoneyDoc breadcrumbs only).

        :param location_with_name: Destination path.
        """
        self._api_client.request_and_download(url="{}{}".format(self.url, "download_breadcrumb_honeydoc/"),
                                              destination_path=location_with_name)


class BreadcrumbCollection(EditableCollection):
    """
    A subset of breadcrumbs in the system.

    This entity will be returned by :py:attr:`api_client.APIClient.breadcrumbs`.
    """

    MODEL_CLASS = Breadcrumb

    def create(self, name, breadcrumb_type, file_field_name=None, file_path=None, **kwargs):
        """
        Create a new breadcrumb.

        :param name: An internal name for the breadcrumb.
        :param breadcrumb_type: The type of breadcrumb. See options for a list \
        of available breadcrumb types.
        :param file_field_name: For breadcrumbs requiring a file, the name of the
        breadcrumb field expected to contain the file content.
        :param file_path: For breadcrumbs requiring a file, the path to the file to upload.
        :param kwargs: Other parameters relevant for the desired breadcrumb type. See options \
        for more information.
        """
        files = {file_field_name: open(file_path, "rb")} if file_field_name else None
        data = dict(
            name=name,
            breadcrumb_type=breadcrumb_type
        )
        data.update(kwargs)
        return self.create_item(data, files=files)


class AlertProcessDLL(BaseEntity):
    """
    A DLL file that was used by an attacker's process.
    """
    def download_file(self, destination_path):
        """
        Download the DLL file to the local disk

        :param destination_path: Location on the disk where you want to save the file.
        """
        self._api_client.request_and_download(
            url="{url}{download_file_suffix}/".format(url=self.url,
                                                      download_file_suffix="download_file"),
            destination_path=destination_path)


class AlertProcessDLLCollection(Collection):
    """
    DLL files associated with a specific binary attack tool, fetched by the Forensic Puller.

    This entity will be returned by calling :py:meth:`AlertProcess.get_dlls`
    """

    MODEL_CLASS = AlertProcessDLL
    URL_SUFFIX = "dll"

    def __init__(self, api_client, alert_process, obj_class=None):
        super(AlertProcessDLLCollection, self).__init__(api_client, obj_class)
        self.alert_process = alert_process

    def _get_url(self):
        return "{process_url}{suffix}/".format(process_url=self.alert_process.url,
                                               suffix=self.URL_SUFFIX)


class AlertProcess(BaseEntity):
    """
    A suspicious process that has been detected on an attacker's endpoint by the Forensic Puller.

    For more information about the Forensic Puller, navigate to User Menu > User Manual.
    """

    def get_dlls(self):
        """
        Get a generator of the DLL files that were used by the process.
        """
        return AlertProcessDLLCollection(self._api_client, alert_process=self)

    def download_file(self, destination_path):
        """
        Download the attacker's tool to your local disk

        :param destination_path: Location on the disk where you want to save the file.
        """
        self._api_client.request_and_download(
            url="{url}{download_file_suffix}/".format(url=self.url,
                                                      download_file_suffix="download_file"),
            destination_path=destination_path)

    def download_minidump(self, destination_path):
        """
        Download minidump of the attacker's process

        :param destination_path: Location on the disk where you want to save the file.
        """
        self._api_client.request_and_download(
            url="{url}{download_file_suffix}/".format(url=self.url,
                                                      download_file_suffix="download_minidump"),
            destination_path="{}.dump".format(destination_path))


class AlertProcessCollection(Collection):
    """
    A subset of the processes associated with a specific alert.

    This entity will be returned by calling :py:meth:`api_client.Alert.get_processes`
    """
    MODEL_CLASS = AlertProcess
    URL_SUFFIX = "process"

    def __init__(self, api_client, alert, obj_class=None):
        super(AlertProcessCollection, self).__init__(api_client, obj_class)
        self.alert = alert

    def _get_url(self):
        return "{alert_url}{suffix}/".format(alert_url=self.alert.url, suffix=self.URL_SUFFIX)


class Alert(BaseEntity):
    """
    An alert is automatically generated by the system every time an attacker interacts with the
    decoy.

    The alert contains the information of a detected attack: which code was executed,
    which query was run on the DB, which SMB shares were accessed, etc.
    """

    NAME = "alert"
    PROCESSES_URL_SUFFIX = "processes"

    def delete(self):
        """
        Delete the alert
        """
        self._api_client.api_request(self.url, "delete")

    def download_image_file(self, location_with_name):
        """
        Download the image file of the executed code.

        :param location_with_name: Download destination path.
        """
        self._api_client.request_and_download(url="{}{}".format(self.url, "download_image_file/"),
                                              destination_path="{}.bin".format(location_with_name))

    def download_memory_dump_file(self, location_with_name):
        """
        Download memory dump of the executed code.

        :param location_with_name: Download destination path.
        """
        self._api_client.request_and_download(url="{}{}".format(self.url, "download_memory_dump_file/"),
                                              destination_path="{}.bin".format(location_with_name))

    def download_network_capture_file(self, location_with_name):
        """
        Download alert info in pcap format.

        :param location_with_name: Download destination path.
        """
        self._api_client.request_and_download(url="{}{}".format(self.url, "download_network_capture_file/"),
                                              destination_path="{}.pcap".format(location_with_name))

    def download_stix_file(self, location_with_name):
        """
        Download alert info in STIX format.

        :param location_with_name: Download destination path.
        """
        self._api_client.request_and_download(url="{}{}".format(self.url, "download_stix_file/"),
                                              destination_path="{}.xml".format(location_with_name))

    def get_processes(self):
        """
        Get a generator of all the processes associated with the alert.

        Supported versions: MazeRunner 1.7.0 and above.
        """
        return AlertProcessCollection(api_client=self._api_client, alert=self)


class AlertCollection(Collection):
    """
    A subset of the alerts in the system.

    This entity will be returned by :py:attr:`api_client.APIClient.alerts`.
    """

    MODEL_CLASS = Alert

    def __init__(self, api_client, filter_enabled=False, only_alerts=False, alert_types=None,
                 start_date=None, end_date=None, id_greater_than=None, username=None, source=None,
                 keywords=None, decoy_name=None):
        """
        :param api_client: The connection instance.
        :param filter_enabled: Whether this is a filtered collection.
        :param only_alerts: Filter out alerts in status 'Ignore' and 'Mute'.
        :param alert_types: E.g., code, HTTP, etc. See params() for the full list.
        :param start_date: The beginning of the date range, formatted dd/mm/yyyy.
        :param end_date: The end of the date range, formatted dd/mm/yyyy.
        :param id_greater_than: Filter alerts to see only alerts that occur after this ID.
        :param username: The breadcrumb's username, which the attacker used to log in.
        :param source: The IP or hostname of the attacker's endpoint.
        :param keywords: Search main fields for these keywords.
        :param decoy_name: The name of the decoy that was attacked.
        """
        super(AlertCollection, self).__init__(api_client)
        self.filter_enabled = filter_enabled
        self.only_alerts = only_alerts
        self.alert_types = alert_types
        self.start_date = start_date
        self.end_date = end_date
        self.id_greater_than = id_greater_than
        self.username = username
        self.source = source
        self.keywords = keywords
        self.decoy_name = decoy_name

    def _get_query_params(self):
        return dict(filter_enabled=self.filter_enabled,
                    only_alerts=self.only_alerts,
                    alert_types=self.alert_types,
                    per_page=ENTRIES_PER_PAGE,
                    start_date=self.start_date,
                    end_date=self.end_date,
                    id_gt=self.id_greater_than,
                    username=self.username,
                    source=self.source,
                    keywords=self.keywords,
                    decoy_name=self.decoy_name)

    def filter(self, filter_enabled=False, only_alerts=False, alert_types=None,
               start_date=None, end_date=None, id_greater_than=None, username=None, source=None,
               keywords=None, decoy_name=None):
        """
        Get alerts by query.

        :param filter_enabled: When False, all the filtering params will be ignored.
        :param only_alerts: Only take alerts in 'Alert' status (exclude those in 'Mute' and \
        'Ignore' status).
        :param alert_types: A list of alert types.
        :param start_date: The beginning of the date range, formatted dd/mm/yyyy.
        :param end_date: The end of the date range, formatted dd/mm/yyyy.
        :param id_greater_than: Filter alerts to see only alerts that occur after this ID.
        :param username: The breadcrumb's username, which the attacker used to log in.
        :param source: The IP or hostname of the attacker's endpoint.
        :param keywords: Search main fields for these keywords.
        :param decoy_name: The name of the decoy that was attacked.
        :return: A filtered :class:`api_client.AlertCollection`.
        """
        formatted_alert_types = " ".join(alert_types) if alert_types else ""
        return AlertCollection(self._api_client,
                               filter_enabled=filter_enabled,
                               only_alerts=only_alerts,
                               alert_types=formatted_alert_types,
                               start_date=start_date,
                               end_date=end_date,
                               id_greater_than=id_greater_than,
                               username=username,
                               source=source,
                               keywords=keywords,
                               decoy_name=decoy_name)

    def export(self, location_with_name):
        """
        Export all alerts to CSV.

        :param location_with_name: Download destination file.
        """
        self._api_client.request_and_download(url="{}{}".format(self._get_url(), "export/"),
                                              destination_path="{}.csv".format(location_with_name),
                                              query_params=self._get_query_params())

    def delete(self, selected_alert_ids=None, delete_all_filtered=False):
        """
        Delete alerts by ID list or by filter.

        :param selected_alert_ids: List of alerts to be deleted.
        :param delete_all_filtered: Delete alerts by query, rather than by ID list. See \
        example below.

        Example 1: Delete alerts by ID list::

            client = mazerunner.connect(...)
            all_alerts = client.alerts.filter()
            all_alerts.delete([101,102,103])

        Example 2: Delete alerts by filter::

            client = mazerunner.connect(...)
            filtered_alerts = client.alerts.filter(alert_types=["share", "http"])
            filtered_alerts.delete(delete_all_filtered=True)
        """
        data = dict(selected_alert_ids=selected_alert_ids,
                    delete_all_filtered=delete_all_filtered)
        query_params = self._get_query_params()
        self._api_client.api_request(url="{}{}".format(self._get_url(), "delete_selected/"),
                                     method="post",
                                     data=data,
                                     query_params=query_params)


class ForensicPullerOnDemand(BaseCollection):
    """
    Forensic Puller on demand.

    This entity will be returned by :py:attr:`api_client.APIClient.forensic_puller_on_demand`.
    """
    URL_EXTENSION = "forensic-puller-on-demand-run"

    def run_on_ip_list(self, ip_list):
        """
        Runs Forensic Puller on a list of IPs.

        :param ip_list: List of IPs.
        """
        data = dict(ip_list=ip_list)
        self._api_client.api_request(
            url=self._get_url(),
            method="post",
            data=data)


class StorageUsageData(BaseCollection):
    """
    Storage usage data.
    This entity will be returned by :py:attr:`api_client.APIClient.storage_usage_data`.
    """
    URL_EXTENSION = "storage-usage"

    def __unicode__(self):
        return unicode(self.details())

    def __str__(self):
        return str(self.details())

    def details(self):
        return self._api_client.api_request(url=self._get_url(), method="get")

    def _get_url(self):
        return self._api_client.api_urls[self.URL_EXTENSION]


class Endpoint(Entity):
    """
    An endpoint represents a single workstation in the organization, and the status
    of the breadcrumbs' deployment to it.
    """

    NAME = "endpoint"

    RELATED_FIELDS = {
        "deployment_group": DeploymentGroup,
    }

    def delete(self):
        """
        Delete the endpoint.
        """
        base_url = self._api_client.api_urls[self.NAME]
        url = "%sdelete_selected/?filter_enabled=true" % base_url
        data = {"selected_endpoints_ids": [self.id]}
        self._api_client.api_request(url, "post", data=data)

    def reassign_to_group(self, deployment_group):
        self._api_client.endpoints.reassign_to_group(deployment_group, [self])

    def clear_deployment_group(self):
        self._api_client.endpoints.clear_deployment_group([self])


class EndpointCollection(EditableCollection):
    """
    A subset of the endpoints in the system.

    This entity will be returned by :py:attr:`api_client.APIClient.endpoints`.
    """

    MODEL_CLASS = Endpoint
    UNASSIGN_FROM_DEPLOYMENT_GROUP = "unassigned"

    RUN_METHOD_FOR_INSTALL_METHOD = {
        "ZIP": "CMD_DEPLOY",
        "EXE": "EXE_DEPLOY",
        "MSI": "EXE_DEPLOY"
    }

    def __init__(self,
                 api_client,
                 filter_enabled=False,
                 keywords="",
                 statuses=None,
                 deploy_groups=None):
        """
        :param api_client: The connection instance.
        :param filter_enabled: Whether this collection is filtered.
        :param keywords: Keywords by which this collection is filtered.
        :param statuses: A whitelist of the endpoint statuses by which you want to filter.
        :param deploy_groups: A whitelist of the deployment group IDs by which you want to filter.
        """
        super(EndpointCollection, self).__init__(api_client)
        self.filter_enabled = filter_enabled
        self.keywords = keywords
        self.statuses = statuses
        self.deploy_groups = deploy_groups

    def create(self, ip_address=None, dns=None, hostname=None, deployment_group_id=None):
        """
        Create an endpoint.

        Pass at least one of the following parameters: ip_address, dns, or hostname.

        :param deployment_group_id: Id of the deployment group.
        :param ip_address: Address of the endpoint.
        :param dns: FQDN of the endpoint.
        :param hostname: Hostname of the endpoint.
        """
        data = dict(ip_address=ip_address, dns=dns, hostname=hostname, deployment_group=deployment_group_id)
        return self.create_item(data=data)

    def _get_query_params(self):
        return {
            "filter_enabled": self.filter_enabled,
            "keywords": self.keywords,
            "statuses": self.statuses,
            "deploy_groups": self.deploy_groups
        }

    def filter(self, keywords=""):
        """
        Get endpoints by query.

        :param keywords: Search keywords.
        :return: A filtered :class:`api_client.EndpointCollection`.
        """
        return EndpointCollection(api_client=self._api_client,
                                  filter_enabled=True,
                                  keywords=keywords)

    def reassign_to_group(self, deployment_group, endpoints):
        """
        Assign endpoints to a deployment group.

        :param deployment_group: The deployment group to assign to.
        :param endpoints: A list of endpoints that should be assigned.
        """
        data = dict(
            to_group=deployment_group.id,
            selected_endpoints_ids=[e.id for e in endpoints])

        self._api_client.api_request(
            "{}{}".format(self._get_url(), "reassign_selected/"),
            method="POST",
            data=data)

    def clear_deployment_group(self, endpoints):
        """
        Unassign specified endpoints from all deployment groups.

        :param endpoints: A list of endpoints that should be unassigned.
        """
        data = dict(
            to_group=self.UNASSIGN_FROM_DEPLOYMENT_GROUP,
            selected_endpoints_ids=[ep.id for ep in endpoints])

        self._api_client.api_request(
            "{}{}".format(self._get_url(), "reassign_selected/"),
            method="POST",
            data=data)

    def _get_run_method(self, install_method):
        if install_method not in self.RUN_METHOD_FOR_INSTALL_METHOD:
            raise InvalidInstallMethodError("Invalid install method: %s" % install_method)
        return self.RUN_METHOD_FOR_INSTALL_METHOD[install_method.upper()]

    def clean_filtered(self,
                       install_method,
                       username,
                       password,
                       domain=""):
        """
        Uninstall breadcrumbs from all of the endpoints matching the filter.

        :param install_method: Uninstaller format (EXE/MSI/ZIP).
        :param username: Local or domain username. MazeRunner will use this to access the endpoint.
        :param password: Password for that user.
        :param domain: The domain where that user is registered. Leave blank for local user.
        """

        self._api_client.api_request(url="{}{}".format(self._get_url(), "clean_selected/"),
                                     method="POST",
                                     query_params=self._get_query_params(),
                                     data={
                                         "clean_all_filtered": True,
                                         "username": username,
                                         "password": {
                                             "value": password
                                         },
                                         "domain": domain,
                                         "run_method": self._get_run_method(install_method),
                                         "install_method": install_method
                                     })

    def clean_by_endpoints_ids(self,
                               endpoints_ids,
                               install_method,
                               username,
                               password,
                               domain=""):
        """
        Uninstall breadcrumbs from all of the specified endpoint IDs.

        :param endpoints_ids: List of IDs of the endpoints from which we want to remove breadcrumbs.
        :param install_method: Uninstaller format (EXE/MSI/ZIP).
        :param username: Local or domain username. MazeRunner will use this to access the endpoint.
        :param password: Password for that user.
        :param domain: The domain where that user is registered. Leave blank for local user.
        """
        self._api_client.api_request(url="{}{}".format(self._get_url(), "clean_selected/"),
                                     method="POST",
                                     data={
                                         "selected_endpoints_ids": endpoints_ids,
                                         "username": username,
                                         "password": {
                                             "value": password
                                         },
                                         "domain": domain,
                                         "run_method": self._get_run_method(install_method),
                                         "install_method": install_method
                                     })

    def delete_filtered(self):
        """
        Delete all the endpoints matching the filter.
        """
        self._api_client.api_request(url="{}{}".format(self._get_url(), "delete_selected/"),
                                     method="POST",
                                     query_params=self._get_query_params(),
                                     data={
                                         "delete_all_filtered": True
                                     })

    def delete_by_endpoints_ids(self, endpoints_ids):
        """
        Delete all the endpoints in the list.

        :param endpoints_ids: List of the endpoint IDs to be deleted.
        """
        self._api_client.api_request(url="{}{}".format(self._get_url(), "delete_selected/"),
                                     method="POST",
                                     data={
                                         "selected_endpoints_ids": endpoints_ids,
                                     })

    def export_filtered(self):
        """
        Export all filtered endpoints to CSV.
        """
        return self._api_client.api_request(url="{}{}".format(self._get_url(), "export/"),
                                            query_params=self._get_query_params(),
                                            expect_json_response=False)

    def filter_data(self):
        """
        Get the available values for the endpoint filters.
        """
        return self._api_client.api_request(url="{}{}".format(self._get_url(), "filter_data/"))

    def params(self):
        raise NotImplementedError


class BackgroundTask(BaseEntity):
    """
    A background task represents the progress of a request that is not accomplished immediately, due
    to its potential to take a long time to process.
    Examples of requests that create background tasks include deployment on endpoints, and importing
    the organization structure from Active Directory.
    """
    NAME = "background-task"

    def stop(self):
        """
        Stop task.
        """
        self._api_client.api_request("{}{}".format(self.url, "stop/"), "post")


class BackgroundTaskCollection(Collection):
    """
    A subset of background tasks in the system.

    This entity will be returned by :py:attr:`api_client.APIClient.background_tasks`.
    """

    MODEL_CLASS = BackgroundTask

    def __init__(self, api_client, running=True):
        """
        :param api_client: The connection instance.
        :param running: If True, shows running tasks. Otherwise, shows completed tasks.
        """
        super(BackgroundTaskCollection, self).__init__(api_client)
        self.running = running

    def _get_query_params(self):
        return dict(running=self.running,)

    def filter(self, running=True):
        """
        Get background tasks by query.

        :param running: When True, running and paused tasks are returned. When False, stopped and \
        completed tasks are returned.
        :return: A filtered :class:`api_client.BackgroundTaskCollection`.
        """
        return BackgroundTaskCollection(self._api_client, running=running)

    def acknowledge_all_complete(self):
        """
        Acknowledge all tasks with the status 'stopped' or 'complete'.
        """
        self._api_client.api_request("{}{}".format(self._get_url(), "acknowledge_all/"), "post")

    def params(self):
        raise NotImplementedError


class AlertPolicy(BaseEntity):
    """
    An alert policy (aka "system-wide rule") is a configuration defining the severity of each
    alert type. The options are:

    - 0 = Ignore
    - 1 = Mute
    - 2 = Alert
    """
    NAME = "alert-policy"

    def update_to_status(self, to_status):
        """
        Update the desired alert level of the given alert type.

        :param to_status: The name of the new 'to_status' of the policy.
        """
        data = dict(to_status=to_status)
        response = self._api_client.api_request(self.url, "put", data=data)
        self._update_entity_data(response)


class AlertPolicyCollection(Collection):
    """
    A subset of the alert policies (aka system-wide rules) in the system.

    This entity will be returned by :py:attr:`api_client.APIClient.alert_policies`.
    """
    MODEL_CLASS = AlertPolicy

    def __len__(self):
        query_params = self._get_query_params()
        response = self._api_client.api_request(self._get_url(), query_params=query_params)
        return len(response)

    def __iter__(self):
        query_params = self._get_query_params()
        response = self._api_client.api_request(self._get_url(), query_params=query_params)
        for item_data in response:
            yield self._obj_class(self._api_client, item_data)

    def reset_all_to_default(self):
        """
        Reset the 'to_status' of all alert policies to their original system default.
        """
        self._api_client.api_request("{}{}".format(self._get_url(), "reset_all/"), "post")


class CIDRMapping(BaseEntity):
    """
    This represents a CIDR block and (optional) a deployment group with which it should be
    associated. The daily CIDR block importer, if enabled, will scan daily all of the endpoints
    in the CIDR mapping range, and will create an endpoint entity for any IP in that range that
    has a reverse DNS record or an NBNS name. If a deployment group was configured for that CIDR
    mapping, the daily CIDR block importer will also assign that deployment
    group to endpoints that were just imported or did not have one configured.
    """
    NAME = "cidr-mapping"

    def generate_endpoints(self):
        """
        Scan the CIDR block and import the endpoints.
        """
        return self._api_client.api_request("{}{}".format(self.url, "generate_endpoints/"),
                                            method="post",
                                            data={
                                                "reassign": False
                                            })

    def delete(self):
        """
        Delete this record.
        """
        self._api_client.api_request(self.url, "delete")


class CIDRMappingCollection(UnpaginatedEditableCollection):
    """
    A subset of the CIDR mappings in the system.

    This entity will be returned by :py:attr:`api_client.APIClient.cidr_mappings`.
    """
    MODEL_CLASS = CIDRMapping

    def create(self, cidr_block, deployment_group, comments, active):
        """
        Create a new CIDR mapping.

        :param cidr_block: The CIDR block from which the endpoints should be imported. E.g., \
        192.168.0.1/24.
        :param deployment_group: Optional. If specified, this deployment group will be assigned \
        to newly imported endpoints and endpoints that were previously unassigned.
        :param comments: Optional. Comments about the CIDR block.
        :param active: Whether this block should be included in the import.
        """
        return self.create_item({
            "cidr_block": cidr_block,
            "deployment_group": deployment_group,
            "comments": comments,
            "active": active
        })

    def generate_all_endpoints(self):
        """
        Scan all the active CIDR blocks in the system and import all of their endpoints.
        """
        return self._api_client.api_request("{}{}".format(self._get_url(),
                                                          "generate_all_endpoints/"),
                                            method="post",
                                            data={
                                                "reassign": False
                                            })

    def params(self):
        raise NotImplementedError


class ActiveSOCEvent(Entity):
    """
    A message to be sent to a SOC interface.
    """

    NAME = "api-soc"


class ActiveSOCEventCollection(EditableCollection):
    """
    Use this when you want to use MazeRunner's ActiveSOC or Responder features, but the SOC
    application that you use is not supported by the built-in MazeRunner integration.
    In order to use these features, first create a SOC interface of the type "SOC via MazeRunner API",
    give it a name, and then send events to that name.
    """

    MODEL_CLASS = ActiveSOCEvent

    def create(self, soc_name, event_dict):
        """
        Submit a single event to the SOC interface.

        :param soc_name: The name of the SOC interface as configured on the SOC screen in \
        MazeRunner.
        :param event_dict: An event dict to be sent.
        """
        return self.create_multiple_events(soc_name, [event_dict])

    def create_multiple_events(self, soc_name, events_dicts):
        """
        Submit multiple events to the SOC interface.

        :param soc_name: The name of the SOC interface as configured on the SOC screen in \
        MazeRunner.
        :param events_dicts: A list of event dicts to be sent.
        """

        data = dict(
            source=soc_name,
            data=events_dicts
        )
        self._api_client.api_request(self._get_url(), "post", data=data)

    def params(self):
        raise NotImplementedError

    def create_item(self, data, files=None):
        raise NotImplementedError

    def get_item(self, id):
        raise NotImplementedError


class AuditLogLine(Entity):
    """
    A message from the server's audit log
    """
    NAME = "audit-log"


class AuditLogLineCollection(Collection):
    """
    Use this to access MazeRunner's audit log.

    This entity will be returned by :py:attr:`api_client.APIClient.audit_log`.
    """
    MODEL_CLASS = AuditLogLine

    def __init__(self, api_client, filter_enabled=False, item=None, username=None, event_type=None, keywords=None,
                 start_date=None, end_date=None, object_ids=None, category=None):
        super(AuditLogLineCollection, self).__init__(api_client)
        self.filter_enabled = filter_enabled
        self.end_date = end_date
        self.start_date = start_date
        self.username = username
        self.category = category
        self.event_type = event_type
        self.object_ids = object_ids
        self.item = item
        self.keywords = keywords

    def _get_query_params(self):
        return {'filter_enabled': self.filter_enabled,
                'end_date': self.end_date,
                'start_date': self.start_date,
                'per_page': ENTRIES_PER_PAGE,
                'username[]': self.username,
                'category[]': self.category,
                'event_type[]': self.event_type,
                'object_ids': self.object_ids,
                'item': self.item}

    def filter(self, filter_enabled=True, item=None, username=None, event_type=None,
               start_date=None, end_date=None, object_ids=None, category=None):

        for param_name, param in dict(username=username,
                                      event_type=event_type,
                                      category=category).iteritems():
            if param and type(param) != list:
                raise BadParamError("{} has to be a list!".format(param_name))
        return AuditLogLineCollection(self._api_client,
                                      filter_enabled=filter_enabled,
                                      end_date=end_date,
                                      start_date=start_date,
                                      username=username,
                                      category=category,
                                      event_type=event_type,
                                      object_ids=object_ids,
                                      item=item)

    def delete(self):
        self._api_client.api_request("".join([self._get_url(), "delete_audit_log/"]), method="post")


class APIClient(object):
    """
    This is the starting point for any interaction with MazeRunner.

    :param host: The hostname or IP address of MazeRunner.
    :param api_key: API key ID. See below how to get one.
    :param api_secret: Secret key. See below how to get one.
    :param certificate: Path to certificate file. See below how to get one.

    How to get your API key and certificate:

        - Open your browser and log in to MazeRunner.
        - Click the gear icon on the top right corner of the screen and select "Manage API keys".
        - Click "Download SSL certificate" and save the file.
        - Click "Create API key".
        - Type a description and click "Create".
        - The api_key will appear as "Key ID".
        - The api_secret will appear as "Secret Key".

    Example::

            client = mazerunner.connect(ip_address="1.2.3.4",
                                           api_key="my-api-key",
                                           api_secret="my-api-secret",
                                           certificate="/path/to/MazeRunner.crt")

            my_service = client.services.get_item(id=8)
    """

    def __init__(self, host, api_key, api_secret, certificate):
        """
        :param host: IP or DNS of MazeRunner.
        :param api_key: Appears as 'KeyID' in the New API Key screen.
        :param api_secret: Appears as 'Secret Key' in the New API Key screen.
        :param certificate: Path to the server's SSL certificate. If False or None, SSL \
        verification is skipped.
        """
        self._auth = requests_hawk.HawkAuth(id=api_key, key=api_secret, algorithm="sha256")
        if certificate is None:
            self._certificate = False
        else:
            self._certificate = certificate
        self._base_url = "https://%(host)s" % dict(host=host)
        self._session = requests.Session()
        self.api_urls = self.api_request("/api/v1.0/")

    def api_request(self,
                    url,
                    method="get",
                    query_params=None,
                    data=None,
                    files=None,
                    stream=False,
                    expect_json_response=True):
        """
        Execute a synchronous API request against MazeRunner and return the result.

        :param url: The request url.
        :param method: HTTP method (get, post, put, patch, delete).
        :param query_params: A dict of the request query parameters.
        :param data: Request body.
        :param files: Files to be sent with the request.
        :param stream: Use stream.
        :param expect_json_response: If True (default), the function will expect an \
            application/json Content-Type in the response, and will return a parsed object \
            as a result. If the response is not in JSON format, a ValidationError or ValueError will be raised.

        """
        if not url.startswith("http"):
            url = self._base_url + url

        parsed = urlparse.urlparse(url)
        parsed_no_query = urlparse.ParseResult(
            scheme=parsed.scheme,
            netloc=parsed.netloc,
            path=parsed.path,
            params=parsed.params,
            query="",
            fragment=parsed.fragment)
        url = urlparse.urlunparse(parsed_no_query)
        query = {query_param_name: set(query_param_value)
                 for query_param_name, query_param_value
                 in urlparse.parse_qs(parsed.query).items()}
        if query_params:
            query.update(query_params)
        query_params = query

        request_args = dict(
            method=method,
            url=url,
            params=query_params,
            auth=self._auth
        )
        if not files:
            request_args["json"] = data
        else:
            request_args["data"] = data
            request_args["files"] = files

        req = requests.Request(**request_args)
        resp = self._session.send(req.prepare(), verify=self._certificate, stream=stream)

        if str(resp.status_code).startswith("4"):
            raise ValidationError(resp.status_code, resp.content)
        if str(resp.status_code).startswith("5"):
            raise ServerError(resp.status_code, resp.content)

        # If stream, return the response as is
        if stream:
            return resp

        if method == "delete" or resp.status_code == NO_CONTENT:
            return None

        content_type = resp.headers.get("Content-Type", None)

        if not expect_json_response:
            return resp.content

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

    def request_and_download(self, url, destination_path, query_params=None):
        data = self.api_request(url, stream=True, query_params=query_params)
        with open(destination_path, "wb") as f:
            data.raw.decode_content = True
            shutil.copyfileobj(data.raw, f)

    @property
    def decoys(self):
        """
        Get a :class:`~api_client.DecoyCollection` instance, on which you can
        perform CRUD operations.

        Example::

            client = mazerunner.connect(...)
            backup_server_story_decoy = client.decoys.create(
                name="backup_server_decoy",
                os="Windows_Server_2012",
                hostname="backupserver",
                vm_type="KVM")

            old_decoy = client.decoys.get_item(id=5)
            old_decoy.delete()
        """
        return DecoyCollection(self)

    @property
    def services(self):
        """
        Get a :class:`api_client.ServiceCollection` instance, on which you can
        perform CRUD operations.

        Example::

            client = mazerunner.connect(...)
            app_db_service = client.services.create(
                name="app_db_service",
                service_type="mysql")
        """
        return ServiceCollection(self)

    @property
    def deployment_groups(self):
        """
        Get a :class:`api_client.DeploymentGroupCollection` instance, on which you can
        perform CRUD operations.

        Example::

            client = mazerunner.connect(...)
            hr_deployment_group = client.deployment_groups.create(
                name="breadcrumbs_for_hr_machines")
        """
        return DeploymentGroupCollection(self)

    @property
    def breadcrumbs(self):
        """
        Get a :class:`api_client.BreadcrumbCollection` instance, on which you can
        perform CRUD operations.

        Example::

            client = mazerunner.connect(...)
            mysql_breadcrumb = client.breadcrumbs.create(
                breadcrumb_type="mysql",
                name="mysql_breadcrumb",
                deploy_for="root",
                installation_type="mysql_history")
            """
        return BreadcrumbCollection(self)

    @property
    def alerts(self):
        """
        Get an :class:`api_client.AlertCollection` instance, on which you can
        perform read and delete operations.

        Example::

            client = mazerunner.connect(...)
            code_alerts = client.alerts.filter(alert_types=["code"])
        """
        return AlertCollection(self)

    @property
    def forensic_puller_on_demand(self):
        """
        Get an :class:`api_client.ForensicPullerOnDemand` instance, on which you can
        perform read and delete operations.

        Example::

            client = mazerunner.connect(...)
            code_alerts = client.forensic_puller_on_demand.run_on_ip_list(ip_list=["192.168.1.1"])
        """
        return ForensicPullerOnDemand(self)

    @property
    def storage_usage(self):
        """
        Get an :class:`api_client.StorageUsageData`
        """
        return StorageUsageData(self)

    @property
    def endpoints(self):
        """
        Get an :class:`api_client.EndpointCollection` instance, on which you can
        perform CRUD operations.

        Example::

            client = mazerunner.connect(...)
            code_alerts = client.endpoints.filter(keywords="hr_workstation_")
        """
        return EndpointCollection(self)

    @property
    def alert_policies(self):
        """
        Get an :class:`api_client.AlertPolicyCollection` instance, on which you can
        perform update operations.

        Example::

            client = mazerunner.connect(...)
            code_alerts = client.alert_policies.reset_all()
        """
        return AlertPolicyCollection(self)

    @property
    def background_tasks(self):
        """
        Get a :class:`api_client.BackgroundTaskCollection` instance, on which you can
        perform read and update operations.

        Example::

            client = mazerunner.connect(...)
            completed_tasks = client.background_tasks.filter(running=False)
        """
        return BackgroundTaskCollection(self)

    @property
    def active_soc_events(self):
        """
        Get an :class:`api_client.ActiveSOCEventCollection` instance. You
        can use this to emit MazeRunner API interface events.

        Example::

            client = mazerunner.connect(...)
            self.active_soc_events.create_multiple_events("my-soc-interface-name", [{
                "ComputerName": "TEST_ENDPOINT1",
                "EventCode": 4625
            },{
                "ComputerName": "TEST_ENDPOINT2",
                "EventCode": 529
            }])
        """
        return ActiveSOCEventCollection(self)

    @property
    def cidr_mappings(self):
        """
        Get a :class:`api_client.CIDRMappingCollection` instance. You can use this to
        import, in bulk, endpoints by their reverse DNS record.

        Example::

            client = mazerunner.connect(...)
            developers_segment = client.cidr_mapping.create(
                cidr_block="192.168.5.0/24",
                deployment_group=5,
                comments="R&D",
                active=True)
            developers_segment.generate_endpoints()
        """
        return CIDRMappingCollection(self)

    @property
    def audit_log(self):
        return AuditLogLineCollection(self)
