import json
import logging

import pytest

import mazerunner
import os

from utils import TimeoutException, wait_until

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("APITest")
logger.setLevel(logging.INFO)


class MachineStatus(object):
    NOT_SEEN = "not_seen"
    ACTIVE = "active"
    INACTIVE = "inactive"


class APITest(object):
    def setup_method(self, method):
        logger.debug("setup_method called")
        ip_address = pytest.config.option.ip_address

        with open(pytest.config.option.json_credentials, 'rb') as file_reader:
            json_dict = json.load(file_reader)
            api_key = json_dict["id"]
            api_secret = json_dict["secret"]

        self.client = mazerunner.connect(
            ip_address=ip_address,
            api_key=api_key,
            api_secret=api_secret,
            certificate=None)

        self.deployment_groups = self.client.deployment_groups
        self.breadcrumbs = self.client.breadcrumbs
        self.services = self.client.services
        self.decoys = self.client.decoys

        self.entities_for_cleanup = []
        self.file_paths_for_cleanup = []

    def teardown_method(self, method):
        logger.debug("teardown_method called")
        # clean used entities:
        for entity in self.entities_for_cleanup:
            if entity.NAME == "deployment-group" and getattr(entity, "persist", False):
                continue
            entity.delete()
        # clean files:
        for file_path in self.file_paths_for_cleanup:
            if os.path.exists(file_path):
                os.remove(file_path)

    def valid_decoy_status(self, decoy, wanted_statuses):
        logger.debug("valid_decoy_status called")
        decoy.load()
        return decoy.machine_status in wanted_statuses

    def wait_for_decoy_status(self, decoy, wanted_statuses, timeout):
        logger.info("wait_for_decoy_status called")
        logger.info("waiting up to %d seconds", timeout)
        try:
            wait_until(
                self.valid_decoy_status,
                decoy=decoy,
                wanted_statuses=wanted_statuses,
                check_return_value=True,
                total_timeout=timeout,
                interval=1,
                exc_list=[Exception]
            )
            return True

        except TimeoutException:
            return False

    def create_decoy(self, decoy_params):
        logger.debug("create_decoy called")
        # create decoy and wait for initial status:
        decoy = self.decoys.create(**decoy_params)
        self.wait_for_decoy_status(decoy, wanted_statuses=[MachineStatus.NOT_SEEN], timeout=60*5)
        logger.info("decoy {0} created".format(decoy_params["name"]))

        return decoy

    def power_on_decoy(self, decoy):
        decoy.power_on()
        self.wait_for_decoy_status(decoy, wanted_statuses=[MachineStatus.ACTIVE], timeout=60 * 10)
        logger.info("decoy {0} is active".format(decoy.name))

    def power_off_decoy(self, decoy):
        decoy.power_off()
        self.wait_for_decoy_status(decoy, wanted_statuses=[MachineStatus.NOT_SEEN, MachineStatus.INACTIVE],
                                   timeout=60 * 10)
        logger.info("decoy {0} is inactive".format(decoy.name))

    def assert_entity_name_in_collection(self, entity_name, collection):
        assert any(entity.name == entity_name for entity in collection)

    def assert_entity_name_not_in_collection(self, entity_name, collection):
        assert not any(entity.name == entity_name for entity in collection)


SSH_GROUP_NAME = "ssh_deployment_group"
SSH_BREADCRUMB_NAME = "ssh_breadcrumb"
SSH_SERVICE_NAME = "ssh_service"
SSH_DECOY_NAME = "ssh_decoy"

SSH_GROUP_NAME_UPDATE = "ssh_deployment_group_update"
SSH_BREADCRUMB_NAME_UPDATE = "ssh_breadcrumb_update"
SSH_SERVICE_NAME_UPDATE = "ssh_service_update"
SSH_DECOY_NAME_UPDATE = "ssh_decoy_update"

OVA_DECOY = "ova_decoy"


class TestSSH(APITest):
    def test_ssh(self):
        logger.debug("test_ssh called")
        # create deployment group:
        deployment_group = self.deployment_groups.create(name=SSH_GROUP_NAME, description="test deployment group")
        self.assert_entity_name_in_collection(SSH_GROUP_NAME, self.deployment_groups)
        self.entities_for_cleanup.append(deployment_group)
        # create breadcrumb:
        breadcrumb_ssh = self.breadcrumbs.create(name=SSH_BREADCRUMB_NAME, breadcrumb_type="ssh", username="ssh_user",
                                                 password="ssh_pass", deployment_groups=[deployment_group.id])
        self.assert_entity_name_in_collection(SSH_BREADCRUMB_NAME, self.breadcrumbs)
        self.entities_for_cleanup.append(breadcrumb_ssh)
        # create service:
        service_ssh = self.services.create(name=SSH_SERVICE_NAME, service_type="ssh")
        self.assert_entity_name_in_collection(SSH_SERVICE_NAME, self.services)
        self.entities_for_cleanup.append(service_ssh)
        # create decoy:
        decoy_ssh = self.create_decoy(dict(name=SSH_DECOY_NAME, hostname="decoyssh", os="Ubuntu_1404", vm_type="KVM"))
        self.assert_entity_name_in_collection(SSH_DECOY_NAME, self.decoys)
        self.entities_for_cleanup.append(decoy_ssh)
        # connect entities:
        breadcrumb_ssh.connect_to_service(service_ssh.id)
        self.assert_entity_name_in_collection(SSH_SERVICE_NAME, breadcrumb_ssh.attached_services)
        service_ssh.connect_to_decoy(decoy_ssh.id)
        self.assert_entity_name_in_collection(SSH_DECOY_NAME, service_ssh.attached_decoys)
        # power on decoy:
        self.power_on_decoy(decoy_ssh)
        assert decoy_ssh.machine_status == MachineStatus.ACTIVE
        # get deployment file:
        deployment_file_path = "mazerunner/test_file"
        download_format = "ZIP"
        breadcrumb_ssh.deploy(location_with_name=deployment_file_path, os="Windows", download_type="install",
                              download_format=download_format)
        self.file_paths_for_cleanup.append("{}.{}".format(deployment_file_path, download_format))
        # add / remove deployment group:
        breadcrumb_ssh.remove_from_group(deployment_group.id)
        self.assert_entity_name_not_in_collection(SSH_GROUP_NAME, breadcrumb_ssh.deployment_groups)
        breadcrumb_ssh.add_to_group(deployment_group.id)
        self.assert_entity_name_in_collection(SSH_GROUP_NAME, breadcrumb_ssh.deployment_groups)
        # edit deployment group:
        deployment_group.update(name=SSH_GROUP_NAME_UPDATE, description="test group")
        self.assert_entity_name_in_collection(SSH_GROUP_NAME_UPDATE, self.deployment_groups)
        self.assert_entity_name_not_in_collection(SSH_GROUP_NAME, self.deployment_groups)
        deployment_group.partial_update(name=SSH_GROUP_NAME)
        self.assert_entity_name_in_collection(SSH_GROUP_NAME, self.deployment_groups)
        self.assert_entity_name_not_in_collection(SSH_GROUP_NAME_UPDATE, self.deployment_groups)
        # edit breadcrumb:
        breadcrumb_ssh.update(name=SSH_BREADCRUMB_NAME_UPDATE, username="new_username", password="qqq")
        assert breadcrumb_ssh.username == "new_username"
        self.assert_entity_name_in_collection(SSH_BREADCRUMB_NAME_UPDATE, self.breadcrumbs)
        self.assert_entity_name_not_in_collection(SSH_BREADCRUMB_NAME, self.breadcrumbs)
        breadcrumb_ssh.partial_update(name=SSH_BREADCRUMB_NAME)
        assert breadcrumb_ssh.username == "new_username"
        self.assert_entity_name_in_collection(SSH_BREADCRUMB_NAME, self.breadcrumbs)
        self.assert_entity_name_not_in_collection(SSH_BREADCRUMB_NAME_UPDATE, self.breadcrumbs)
        # edit service:
        service_ssh.update(name=SSH_SERVICE_NAME_UPDATE)
        self.assert_entity_name_in_collection(SSH_SERVICE_NAME_UPDATE, self.services)
        self.assert_entity_name_not_in_collection(SSH_SERVICE_NAME, self.services)
        service_ssh.partial_update(name=SSH_SERVICE_NAME)
        self.assert_entity_name_in_collection(SSH_SERVICE_NAME, self.services)
        self.assert_entity_name_not_in_collection(SSH_SERVICE_NAME_UPDATE, self.services)
        # edit decoy:
        decoy_ssh.update(name=SSH_DECOY_NAME_UPDATE)
        self.assert_entity_name_in_collection(SSH_DECOY_NAME_UPDATE, self.decoys)
        self.assert_entity_name_not_in_collection(SSH_DECOY_NAME, self.decoys)
        decoy_ssh.partial_update(name=SSH_DECOY_NAME)
        self.assert_entity_name_in_collection(SSH_DECOY_NAME, self.decoys)
        self.assert_entity_name_not_in_collection(SSH_DECOY_NAME_UPDATE, self.decoys)
        # disconnect entities:
        breadcrumb_ssh.detach_from_service(service_ssh.id)
        self.assert_entity_name_not_in_collection(SSH_SERVICE_NAME, breadcrumb_ssh.attached_services)
        service_ssh.detach_from_decoy(decoy_ssh.id)
        self.assert_entity_name_not_in_collection(SSH_DECOY_NAME, service_ssh.attached_decoys)
        # power off decoy:
        self.power_off_decoy(decoy_ssh)
        assert decoy_ssh.machine_status == MachineStatus.INACTIVE

    def test_ova(self):
        logger.debug("test_ova called")
        # create decoy:
        ova_decoy = self.create_decoy(dict(name=OVA_DECOY, hostname="ovadecoy", os="Ubuntu_1404", vm_type="OVA"))
        self.assert_entity_name_in_collection(OVA_DECOY, self.decoys)
        self.entities_for_cleanup.append(ova_decoy)
        # download decoy:
        download_file_path = "mazerunner/ova_image"
        ova_decoy.download(location_with_name=download_file_path)
        self.file_paths_for_cleanup.append("{}.ova".format(download_file_path))
