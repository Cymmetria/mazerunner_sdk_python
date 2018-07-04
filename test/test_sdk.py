import StringIO
import csv
import datetime
import json
import logging
import shutil
from stat import S_IRUSR

import pytest
from retrying import retry
from subprocess import Popen

import mazerunner
import os

from mazerunner.api_client import Service, AlertPolicy, Decoy, Breadcrumb, \
    DeploymentGroup, Endpoint, CIDRMapping, BackgroundTask, AuditLogLine, ISO_TIME_FORMAT
from mazerunner.exceptions import ValidationError, ServerError, BadParamError, \
    InvalidInstallMethodError
from utils import TimeoutException, wait_until

CLEAR_SYSTEM_ERROR_MESSAGE = 'System must be clean before running this test. Use the '\
                             '--initial_clean flag to do this automatically'
ENDPOINT_IP_PARAM = 'endpoint_ip'
ENDPOINT_USERNAME_PARAM = 'endpoint_username'
ENDPOINT_PASSWORD_PARAM = 'endpoint_password'

CODE_EXECUTION_ALERT_TYPE = 'code'
FORENSIC_DATA_ALERT_TYPE = 'forensic_puller'

MAZERUNNER_IP_ADDRESS_PARAM = 'ip_address'
API_ID_PARAM = 'id'
API_SECRET_PARAM = 'secret'
MAZERUNNER_CERTIFICATE_PATH_PARAM = 'mazerunner_certificate_path'

ENTITIES_CONFIGURATION = {
    Decoy: [],
    Service: [],
    Breadcrumb: [],
    DeploymentGroup: [1],
    Endpoint: [],
    CIDRMapping: [],
    BackgroundTask: []
}


TEST_DEPLOYMENTS_FILE_PATH = os.path.join(os.path.dirname(__file__), 'test_deployments/dep.zip')
TEST_DEPLOYMENTS_FOLDER_PATH = os.path.dirname(TEST_DEPLOYMENTS_FILE_PATH)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("APITest")
logger.setLevel(logging.INFO)


class AlertNotFoundError(RuntimeError):
    pass


def _clear_deployment_path():
    if os.path.exists(TEST_DEPLOYMENTS_FOLDER_PATH):
        shutil.rmtree(TEST_DEPLOYMENTS_FOLDER_PATH)

    os.makedirs(TEST_DEPLOYMENTS_FOLDER_PATH)


class MachineStatus(object):
    NOT_SEEN = "not_seen"
    ACTIVE = "active"
    INACTIVE = "inactive"


# noinspection PyMethodMayBeStatic,PyAttributeOutsideInit
class APITest(object):

    runslow = pytest.mark.skipif(not pytest.config.getoption('--runslow'),
                                 reason='--runslow not activated')
    lab_dependent = pytest.mark.skipif(not pytest.config.getoption('--lab_dependent'),
                                       reason='--lab_dependent not activated')

    def _assert_clean_system(self):
        for entity_collection in self.disposable_entities:
            existing_ids = {entity.id for entity in entity_collection}
            expected_ids = set(ENTITIES_CONFIGURATION[entity_collection.MODEL_CLASS])

            assert existing_ids == expected_ids, CLEAR_SYSTEM_ERROR_MESSAGE

        assert len(self.background_tasks) == 0, CLEAR_SYSTEM_ERROR_MESSAGE

    def _configure_entities_groups(self):
        self.decoys = self.client.decoys
        self.services = self.client.services
        self.breadcrumbs = self.client.breadcrumbs
        self.deployment_groups = self.client.deployment_groups
        self.alerts = self.client.alerts
        self.alert_policies = self.client.alert_policies
        self.cidr_mappings = self.client.cidr_mappings
        self.endpoints = self.client.endpoints
        self.background_tasks = self.client.background_tasks
        self.audit_log = self.client.audit_log

        self.disposable_entities = [
            self.decoys,
            self.services,
            self.breadcrumbs,
            self.deployment_groups,
            self.endpoints,
            self.cidr_mappings
        ]

    def setup_method(self, method):
        logger.debug("setup_method called")

        with open(pytest.config.option.json_credentials, 'rb') as file_reader:
            json_dict = json.load(file_reader)

        self.lab_endpoint_ip = json_dict.get(ENDPOINT_IP_PARAM)
        self.lab_endpoint_user = json_dict.get(ENDPOINT_USERNAME_PARAM)
        self.lab_endpoint_password = json_dict.get(ENDPOINT_PASSWORD_PARAM)

        self.mazerunner_ip_address = json_dict[MAZERUNNER_IP_ADDRESS_PARAM]
        self.api_key = json_dict[API_ID_PARAM]
        self.api_secret = json_dict[API_SECRET_PARAM]
        self.mazerunner_certificate_path = json_dict[MAZERUNNER_CERTIFICATE_PATH_PARAM]

        self.client = mazerunner.connect(
            ip_address=self.mazerunner_ip_address,
            api_key=self.api_key,
            api_secret=self.api_secret,
            certificate=self.mazerunner_certificate_path)

        self._configure_entities_groups()

        if pytest.config.option.initial_clean:
            self._destroy_new_entities()

        self._assert_clean_system()

        self.file_paths_for_cleanup = []

        _clear_deployment_path()

    def _destroy_new_entities(self):
        for entity_collection in self.disposable_entities:
            for entity in list(entity_collection):
                initial_ids = ENTITIES_CONFIGURATION[entity_collection.MODEL_CLASS]
                if entity.id not in initial_ids:
                    wait_until(entity.delete, exc_list=[ServerError, ValidationError],
                               check_return_value=False)

        self.background_tasks.acknowledge_all_complete()

        wait_until(self._assert_clean_system, exc_list=[AssertionError], check_return_value=False)

    def teardown_method(self, method):
        logger.debug("teardown_method called")

        self._destroy_new_entities()

        # Clean files:
        for file_path in self.file_paths_for_cleanup:
            if os.path.exists(file_path):
                os.remove(file_path)
        _clear_deployment_path()

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
        self.wait_for_decoy_status(decoy,
                                   wanted_statuses=[MachineStatus.NOT_SEEN, MachineStatus.INACTIVE],
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
HONEYDOC_GROUP_NAME = "honeydoc_deployment_group"
HONEYDOC_BREADCRUMB_NAME = "honeydoc_breadcrumb"
HONEYDOC_SERVICE_NAME = "honeydoc_service"
HONEYDOC_SERVICE_SERVER_SUFFIX = "server_suffix"
HONEYDOC_DECOY_NAME = "honeydoc_decoy"

OVA_DECOY = "ova_decoy"


class TestGeneralFlow(APITest):
    def test_api_setup_campaign(self):
        logger.debug("test_api_setup_campaign called")

        # Create deployment group:
        assert {dg.id for dg in self.deployment_groups} == \
               set(ENTITIES_CONFIGURATION[DeploymentGroup])
        deployment_group = self.deployment_groups.create(name=SSH_GROUP_NAME,
                                                         description="test deployment group")
        self.assert_entity_name_in_collection(SSH_GROUP_NAME, self.deployment_groups)
        assert {dg.id for dg in self.deployment_groups} == \
            set(ENTITIES_CONFIGURATION[DeploymentGroup] + [deployment_group.id])

        # Create breadcrumb:
        assert len(self.breadcrumbs) == 0
        breadcrumb_ssh = self.breadcrumbs.create(name=SSH_BREADCRUMB_NAME,
                                                 breadcrumb_type="ssh",
                                                 username="ssh_user",
                                                 password="ssh_pass",
                                                 deployment_groups=[deployment_group.id])
        self.assert_entity_name_in_collection(SSH_BREADCRUMB_NAME, self.breadcrumbs)
        assert len(self.breadcrumbs) == 1

        # Create service:
        assert len(self.services) == 0
        service_ssh = self.services.create(name=SSH_SERVICE_NAME, service_type="ssh", any_user="false")
        self.assert_entity_name_in_collection(SSH_SERVICE_NAME, self.services)
        assert len(self.services) == 1

        # Create decoy:
        assert len(self.decoys) == 0
        decoy_ssh = self.create_decoy(dict(name=SSH_DECOY_NAME,
                                           hostname="decoyssh",
                                           os="Ubuntu_1404",
                                           vm_type="KVM"))
        self.assert_entity_name_in_collection(SSH_DECOY_NAME, self.decoys)
        assert len(self.decoys) == 1

        service_ssh.load()
        breadcrumb_ssh.load()
        assert len(service_ssh.available_decoys) == 1
        assert len(service_ssh.attached_decoys) == 0
        assert len(service_ssh.available_decoys) == 1
        assert len(service_ssh.attached_decoys) == 0
        assert len(breadcrumb_ssh.available_services) == 1
        assert len(breadcrumb_ssh.attached_services) == 0

        # Connect entities:
        breadcrumb_ssh.connect_to_service(service_ssh.id)
        self.assert_entity_name_in_collection(SSH_SERVICE_NAME, breadcrumb_ssh.attached_services)
        service_ssh.connect_to_decoy(decoy_ssh.id)
        self.assert_entity_name_in_collection(SSH_DECOY_NAME, service_ssh.attached_decoys)

        service_ssh.load()
        breadcrumb_ssh.load()
        assert len(service_ssh.available_decoys) == 0
        assert len(service_ssh.attached_decoys) == 1
        assert len(service_ssh.available_decoys) == 0
        assert len(service_ssh.attached_decoys) == 1
        assert len(breadcrumb_ssh.available_services) == 0
        assert len(breadcrumb_ssh.attached_services) == 1

        # Power on decoy:
        self.power_on_decoy(decoy_ssh)
        decoy_ssh.load()
        assert decoy_ssh.machine_status == MachineStatus.ACTIVE

        # Get deployment file:
        deployment_file_path = "mazerunner/test_file"
        download_format = "ZIP"
        breadcrumb_ssh.deploy(location_with_name=deployment_file_path,
                              os="Windows",
                              download_type="install",
                              download_format=download_format)
        self.file_paths_for_cleanup.append("{}.{}".format(deployment_file_path,
                                                          download_format.lower()))

        # Add / remove deployment group:
        breadcrumb_ssh.remove_from_group(deployment_group.id)
        self.assert_entity_name_not_in_collection(SSH_GROUP_NAME, breadcrumb_ssh.deployment_groups)
        breadcrumb_ssh.add_to_group(deployment_group.id)
        self.assert_entity_name_in_collection(SSH_GROUP_NAME, breadcrumb_ssh.deployment_groups)

        # Edit deployment group:
        deployment_group.update(name=SSH_GROUP_NAME_UPDATE, description="test group")
        self.assert_entity_name_in_collection(SSH_GROUP_NAME_UPDATE, self.deployment_groups)
        self.assert_entity_name_not_in_collection(SSH_GROUP_NAME, self.deployment_groups)
        deployment_group.partial_update(name=SSH_GROUP_NAME)
        self.assert_entity_name_in_collection(SSH_GROUP_NAME, self.deployment_groups)
        self.assert_entity_name_not_in_collection(SSH_GROUP_NAME_UPDATE, self.deployment_groups)

        service_ssh.update(name=SSH_SERVICE_NAME_UPDATE, any_user="false")

        breadcrumb_ssh.detach_from_service(service_ssh.id)
        self.assert_entity_name_not_in_collection(SSH_SERVICE_NAME,
                                                  breadcrumb_ssh.attached_services)
        service_ssh.detach_from_decoy(decoy_ssh.id)
        self.assert_entity_name_not_in_collection(SSH_DECOY_NAME, service_ssh.attached_decoys)

        # Power off decoy:
        self.power_off_decoy(decoy_ssh)
        decoy_ssh.load()
        assert decoy_ssh.machine_status == MachineStatus.INACTIVE

        invalid_service = "invalid_service"
        with pytest.raises(ValidationError):
            self.services.create(name=invalid_service, service_type=invalid_service)
        self.assert_entity_name_not_in_collection(invalid_service, self.services)

    def test_honeydoc_breadcrumb(self):
        logger.debug("test_honeydoc_breadcrumb called")
        downloaded_docx_file_path = "test/downloaded.docx"
        self.file_paths_for_cleanup.append(downloaded_docx_file_path)
        deployment_group = self.deployment_groups.create(name=HONEYDOC_GROUP_NAME,
                                                         description="test deployment group")
        breadcrumb_honeydoc = self.breadcrumbs.create(name=HONEYDOC_BREADCRUMB_NAME,
                                                      breadcrumb_type="honey_doc",
                                                      deployment_groups=[deployment_group.id],
                                                      monitor_from_external_host=False,
                                                      file_field_name="docx_file_content",
                                                      file_path="test/sample.docx")
        service_honeydoc = self.services.create(name=HONEYDOC_SERVICE_NAME,
                                                service_type="honey_doc",
                                                server_suffix=HONEYDOC_SERVICE_SERVER_SUFFIX)
        decoy_honeydoc = self.create_decoy(dict(name=HONEYDOC_DECOY_NAME,
                                                hostname="decoyhoneydoc",
                                                os="Ubuntu_1404",
                                                vm_type="KVM"))
        service_honeydoc.load()
        breadcrumb_honeydoc.load()
        self.assert_entity_name_in_collection(HONEYDOC_GROUP_NAME, breadcrumb_honeydoc.deployment_groups)
        breadcrumb_honeydoc.connect_to_service(service_honeydoc.id)
        service_honeydoc.connect_to_decoy(decoy_honeydoc.id)
        service_honeydoc.load()
        breadcrumb_honeydoc.load()
        self.power_on_decoy(decoy_honeydoc)
        decoy_honeydoc.load()
        breadcrumb_honeydoc.download_breadcrumb_honeydoc(downloaded_docx_file_path)
        assert os.path.exists(downloaded_docx_file_path)
        assert os.path.getsize(downloaded_docx_file_path) > 0


class TestDecoy(APITest):
    DECOY_STATUS_ACTIVE = 'active'
    DECOY_STATUS_BOOTING = 'booting'
    DECOY_STATUS_INACTIVE = 'inactive'
    DECOY_STATUS_CONFIGURING = 'configuring'

    @APITest.runslow
    def test_ova(self):
        logger.debug("test_ova called")

        # Create decoy:
        ova_decoy = self.create_decoy(dict(name=OVA_DECOY,
                                           hostname="ovadecoy",
                                           os="Ubuntu_1404",
                                           vm_type="OVA"))
        self.assert_entity_name_in_collection(OVA_DECOY, self.decoys)

        # Download decoy:
        download_file_path = "mazerunner/ova_image"

        # Wait until the decoy becomes available and download the file
        wait_until(ova_decoy.download, location_with_name=download_file_path,
                   check_return_value=False, exc_list=[ValidationError], total_timeout=60*10)

        self.file_paths_for_cleanup.append("{}.ova".format(download_file_path))

    def test_decoy_update(self):
        def _assert_expected_values():
            assert decoy.name == decoy_name
            assert decoy.hostname == decoy_hostname
            assert decoy.os == decoy_os
            assert decoy.vm_type == vm_type

        decoy_name = 'original_decoy_name'
        decoy_hostname = 'decoyssh'
        decoy_os = 'Ubuntu_1404'
        vm_type = 'KVM'

        decoy = self.create_decoy(dict(name=decoy_name,
                                       hostname=decoy_hostname,
                                       os=decoy_os,
                                       vm_type=vm_type))
        _assert_expected_values()
        decoy.load()
        _assert_expected_values()

        # Try to rename the decoy
        decoy_name = 'renamed_decoy'
        decoy.update(name=decoy_name)

        _assert_expected_values()
        decoy.load()
        _assert_expected_values()

    @classmethod
    @retry(stop_max_attempt_number=600, wait_fixed=1000)
    def _wait_for_decoy_status(cls, decoy, desired_status):
        assert decoy.load().machine_status == desired_status

    @classmethod
    def _start_decoy(cls, decoy):
            decoy.power_on()
            cls._wait_for_decoy_status(decoy, cls.DECOY_STATUS_ACTIVE)

    def test_decoy_recreation(self):
        decoy = self.create_decoy(dict(name='original_decoy_name',
                                       hostname='decoyssh',
                                       os='Ubuntu_1404',
                                       vm_type='KVM'))
        self._start_decoy(decoy)
        decoy.recreate()
        self._wait_for_decoy_status(decoy, self.DECOY_STATUS_BOOTING)
        self._wait_for_decoy_status(decoy, self.DECOY_STATUS_ACTIVE)

    def test_test_dns(self):
        decoy = self.create_decoy(dict(name='original_decoy_name',
                                       hostname='decoyssh',
                                       os='Ubuntu_1404',
                                       vm_type='KVM',
                                       dns_address='no.such.dns'))
        self._start_decoy(decoy)
        assert decoy.test_dns() is False

        decoy.power_off()
        self._wait_for_decoy_status(decoy, self.DECOY_STATUS_INACTIVE)

        with pytest.raises(ValidationError):
            decoy.test_dns()


class TestDeploymentGroups(APITest):

    def test_basic_crud(self):
        dep_group = self.deployment_groups.create(name='test_check_conflicts')
        dep_group.update(name='test_check_conflicts1', description='pretty dg')
        assert self.deployment_groups.get_item(dep_group.id).name == 'test_check_conflicts1'
        dep_group.delete()
        with pytest.raises(ValidationError):
            self.deployment_groups.get_item(dep_group.id)

    def test_check_conflicts(self):
        decoy_ssh = self.create_decoy(dict(name=SSH_DECOY_NAME,
                                           hostname="decoyssh",
                                           os="Ubuntu_1404",
                                           vm_type="KVM"))
        service_ssh = self.services.create(name=SSH_SERVICE_NAME, service_type="ssh", any_user="false")
        service_ssh.connect_to_decoy(decoy_ssh.id)

        dep_group = self.deployment_groups.create(name='test_check_conflicts')

        assert dep_group.check_conflicts('Linux') == []
        assert dep_group.check_conflicts('Windows') == []

        bc_ssh1 = self.breadcrumbs.create(name='ssh1',
                                          breadcrumb_type="ssh",
                                          username="ssh_user",
                                          password="ssh_pass")
        bc_ssh1.connect_to_service(service_ssh.id)

        # Make sure we get only numbers
        with pytest.raises(BadParamError):
            bc_ssh1.add_to_group('test_check_conflicts')

        bc_ssh1.add_to_group(dep_group.id)

        assert dep_group.check_conflicts('Linux') == []
        assert dep_group.check_conflicts('Windows') == []

        bc_ssh2 = self.breadcrumbs.create(name='ssh2',
                                          breadcrumb_type="ssh",
                                          username="ssh_user",
                                          password="ssh_pass")
        bc_ssh2.connect_to_service(service_ssh.id)
        bc_ssh2.add_to_group(dep_group.id)

        assert dep_group.check_conflicts('Linux') == []
        assert dep_group.check_conflicts('Windows') == [
            {
                u'error': u"Conflict between breadcrumbs ssh1 and ssh2: "
                          u"Two SSH breadcrumbs can't point to the same "
                          u"user/decoy combination on the same endpoint"
            }
        ]

    def test_deployment(self):
        decoy_ssh = self.create_decoy(dict(name=SSH_DECOY_NAME,
                                           hostname="decoyssh",
                                           os="Ubuntu_1404",
                                           vm_type="KVM"))

        service_ssh = self.services.create(name=SSH_SERVICE_NAME, service_type="ssh", any_user="false")

        bc_ssh = self.breadcrumbs.create(name='ssh1',
                                         breadcrumb_type="ssh",
                                         username="ssh_user",
                                         password="ssh_pass")

        dep_group = self.deployment_groups.create(name='test_check_conflicts')

        service_ssh.connect_to_decoy(decoy_ssh.id)
        bc_ssh.connect_to_service(service_ssh.id)
        bc_ssh.add_to_group(dep_group.id)

        self.power_on_decoy(decoy_ssh)

        def _has_complete_bg_tasks():
            return len([bg_task for bg_task in self.background_tasks.filter(running=False)]) > 0

        def _wait_and_destroy_background_task():
            wait_until(_has_complete_bg_tasks, check_return_value=True)
            self.background_tasks.acknowledge_all_complete()

        def _test_manual_deployment():
            dep_group.deploy(location_with_name=TEST_DEPLOYMENTS_FILE_PATH.replace('.zip', ''),
                             os='Windows',
                             download_type='install')

            assert os.path.exists(TEST_DEPLOYMENTS_FILE_PATH)

            os.remove(TEST_DEPLOYMENTS_FILE_PATH)

            self.deployment_groups.deploy_all(
                location_with_name=TEST_DEPLOYMENTS_FILE_PATH.replace('.zip', ''),
                os='Windows',
                download_format='ZIP')

            assert os.path.exists(TEST_DEPLOYMENTS_FILE_PATH)

            os.remove(TEST_DEPLOYMENTS_FILE_PATH)

        def _test_auto_deployment():
            # Since this runs asynchronously and it has nothing to deploy on, we only want to see
            # that the request was accepted

            dep_group.auto_deploy(username='some-user',
                                  password='some-pass',
                                  install_method='PS_EXEC',
                                  run_method='EXE_DEPLOY',
                                  domain='',
                                  deploy_on="all")

            _wait_and_destroy_background_task()

            self.deployment_groups.auto_deploy_groups(
                username='some-user',
                password='some-pass',
                install_method='PS_EXEC',
                deployment_groups_ids=[1],
                run_method='EXE_DEPLOY',
                domain='',
                deploy_on="all")

            _wait_and_destroy_background_task()

        _test_manual_deployment()
        _test_auto_deployment()

    def forensic_puller_alert_is_shown(self):
        alerts = list(self.alerts.filter(filter_enabled=True,
                                         only_alerts=False,
                                         alert_types=[FORENSIC_DATA_ALERT_TYPE]))
        return bool(alerts)

    @pytest.mark.skip("needs auto deploy setting credentials")
    @APITest.lab_dependent
    def test_forensic_puller_on_demand(self):
        ## TODO: Add setting global deployment credentials here.
        self.client.forensic_puller_on_demand.run_on_ip_list(ip_list=[self.lab_endpoint_ip])
        wait_until(self.forensic_puller_alert_is_shown)

    @APITest.lab_dependent
    def test_deployment_credentials(self):
        assert self.client.deployment_groups.test_deployment_credentials(
            username=self.lab_endpoint_user,
            password=self.lab_endpoint_password,
            addr=self.lab_endpoint_ip,
            install_method='PS_EXEC',
            domain=None
        ) == {'success': True}

        assert self.client.deployment_groups.test_deployment_credentials(
            username=self.lab_endpoint_user,
            password=self.lab_endpoint_password,
            addr='192.168.100.100',
            install_method='PS_EXEC',
            domain=None
        ) == {
            u'reason': u'Endpoint SMB TCP Ports(139, 445) are unreachable',
            u'success': False
        }

        assert self.client.deployment_groups.test_deployment_credentials(
            username=self.lab_endpoint_user,
            password='WrongPassword',
            addr=self.lab_endpoint_ip,
            install_method='PS_EXEC',
            domain=None
        ) == {u'reason': u'Incorrect credentials for endpoint', u'success': False}

        assert self.client.deployment_groups.test_deployment_credentials(
            username='WrongUser',
            password=self.lab_endpoint_password,
            addr=self.lab_endpoint_ip,
            install_method='PS_EXEC',
            domain=None
        ) == {u'reason': u'Incorrect credentials for endpoint', u'success': False}


class TestCollections(APITest):
    def test_pagination(self):
        breadcrumbs_to_create = 55

        created_breadcrumbs_names = ['%s_%s' % (SSH_BREADCRUMB_NAME, breadcrumb_num)
                                     for breadcrumb_num
                                     in range(breadcrumbs_to_create)]

        for breadcrumb_name in created_breadcrumbs_names:
            self.breadcrumbs.create(name=breadcrumb_name,
                                    breadcrumb_type="ssh",
                                    username="ssh_user",
                                    password="ssh_pass")

        assert len(self.breadcrumbs) == breadcrumbs_to_create
        fetched_breadcrumbs = [breadcrumb for breadcrumb in self.breadcrumbs]
        assert len(fetched_breadcrumbs) == breadcrumbs_to_create

        fetched_breadcrumbs_names = [breadcrumb.name for breadcrumb in fetched_breadcrumbs]

        assert set(fetched_breadcrumbs_names) == set(created_breadcrumbs_names)

    def test_get_item(self):
        breadcrumb = self.breadcrumbs.create(name='test_breadcrumb',
                                             breadcrumb_type="ssh",
                                             username="ssh_user",
                                             password="ssh_pass")

        assert self.breadcrumbs.get_item(breadcrumb.id).id == breadcrumb.id

        with pytest.raises(ValidationError):
            assert self.breadcrumbs.get_item(breadcrumb.id + 1)

    def test_params(self):
        assert type(self.decoys.params()) == dict
        assert type(self.services.params()) == dict
        assert type(self.breadcrumbs.params()) == dict


def _get_breadcrumb_config(breadcrumb):
    breadcrumb.deploy(
        location_with_name=TEST_DEPLOYMENTS_FILE_PATH.replace('.zip', ''),
        os='Linux',
        download_type='install',
        download_format='ZIP'
    )

    Popen(['unzip', TEST_DEPLOYMENTS_FILE_PATH], cwd=TEST_DEPLOYMENTS_FOLDER_PATH)
    config_file_path = '%s/utils/config.json' % TEST_DEPLOYMENTS_FOLDER_PATH

    wait_until(os.path.exists, path=config_file_path)

    with open(config_file_path, 'rb') as f:
        return json.load(f)


def _create_private_keys_from_config(config):
    for bc_index, bc in config['install'].iteritems():

        pk = bc.get('private_key')
        bc_id = bc.get('remote_id')
        address = bc.get('address')
        username = bc.get('username')
        login_str = '%s@%s' % (username, address)

        if not pk:
            continue

        key_path = '%s/%s.pem' % (TEST_DEPLOYMENTS_FOLDER_PATH, bc_id)
        with open(key_path, 'wb') as f:
            f.write(pk)
        os.chmod(key_path, S_IRUSR)

        yield login_str, key_path


class TestAlert(APITest):
    def test_alert_download(self):
        def _create_code_exec_alert():
            decoy_ssh = self.create_decoy(dict(name=SSH_DECOY_NAME,
                                               hostname="decoyssh",
                                               os="Ubuntu_1404",
                                               vm_type="KVM"))
            service_ssh = self.services.create(name=SSH_SERVICE_NAME, service_type="ssh", any_user="false")
            service_ssh.connect_to_decoy(decoy_ssh.id)

            bc_ssh1 = self.breadcrumbs.create(name='ssh1',
                                              breadcrumb_type="ssh_privatekey",
                                              username="ssh_user",
                                              deploy_for="root",
                                              installation_type='history')
            bc_ssh1.connect_to_service(service_ssh.id)
            self.power_on_decoy(decoy_ssh)

            config = _get_breadcrumb_config(bc_ssh1)
            login_str, private_key_path = _create_private_keys_from_config(config).next()

            Popen(['ssh', '-o', 'UserKnownHostsFile=/dev/null', '-o',
                   'StrictHostKeyChecking=no', login_str, '-i', private_key_path,
                   'ping -c 10 localhost'])

            wait_until(self._get_first_code_execution_alert, exc_list=[AlertNotFoundError])

            return self._get_first_code_execution_alert()

        def _test_download_alert_files(code_exec_alert):
            image_file = '%s/image' % TEST_DEPLOYMENTS_FOLDER_PATH
            code_exec_alert.download_image_file(image_file)
            assert os.path.exists('%s.bin' % image_file)

            mem_dump = '%s/mem_dump' % TEST_DEPLOYMENTS_FOLDER_PATH
            code_exec_alert.download_memory_dump_file(mem_dump)
            assert os.path.exists('%s.bin' % mem_dump)

            netcap_file = '%s/netcap' % TEST_DEPLOYMENTS_FOLDER_PATH
            code_exec_alert.download_network_capture_file(netcap_file)
            assert os.path.exists('%s.pcap' % netcap_file)

            stix_file = '%s/stix' % TEST_DEPLOYMENTS_FOLDER_PATH
            code_exec_alert.download_stix_file(stix_file)
            assert os.path.exists('%s.xml' % stix_file)

        def _test_delete_single_alert(code_exec_alert):
            code_exec_alert.delete()

            with pytest.raises(ValidationError):
                self.alerts.get_item(code_exec_alert.id)

        def _test_export():
            export_file = '%s/export' % TEST_DEPLOYMENTS_FOLDER_PATH
            self.alerts.export(export_file)
            assert os.path.exists('%s.csv' % export_file)

        def _test_delete_filtered_alerts():
            assert len(self.alerts) > 0

            self.alerts.delete(delete_all_filtered=True)

            assert len(self.alerts) == 0

        code_alert = _create_code_exec_alert()
        _test_download_alert_files(code_alert)
        _test_export()
        _test_delete_single_alert(code_alert)
        _test_delete_filtered_alerts()

    def _get_first_code_execution_alert(self):
        alerts = list(self.alerts.filter(filter_enabled=True,
                                         only_alerts=True,
                                         alert_types=[CODE_EXECUTION_ALERT_TYPE]))
        if not alerts:
            raise AlertNotFoundError

        return alerts[0]

    def test_params(self):
        assert isinstance(self.alerts.params(), dict)


class TestEntity(APITest):
    def test_repr(self):
        service = self.services.create(name=SSH_SERVICE_NAME, service_type="ssh", any_user="false")

        str_service = "<Service: available_decoys=[] name=u'ssh_service' service_type_name=u'SSH' " \
                      "url=u'https://{serv}/api/v1.0/service/{service_id}/' " \
                      "is_active=False attached_decoys=[] any_user={any_user} is_delete_enabled=True " \
                      "service_type=u'ssh' id={service_id}>"\
            .format(serv=self.mazerunner_ip_address, service_id=service.id, any_user=service.any_user)
        assert str(service) == str_service

    def test_get_attribute(self):
        service = self.services.create(name=SSH_SERVICE_NAME, service_type="ssh", any_user="false")
        assert service.name == SSH_SERVICE_NAME

        with pytest.raises(AttributeError):
            _ = service.no_such_attribute

        unloaded_service = Service(self.client, {'id': service.id, 'url': service.url})
        assert unloaded_service.name == SSH_SERVICE_NAME

        with pytest.raises(AttributeError):
            _ = unloaded_service.no_such_attribute

        no_such_service_data = {
            'id': service.id + 1,
            'url': '%s%s/' % (self.client.api_urls['service'], service.id + 1)
        }
        no_such_service = Service(self.client, no_such_service_data)

        with pytest.raises(ValidationError):
            assert no_such_service.name == SSH_SERVICE_NAME

        with pytest.raises(ValidationError):
            _ = no_such_service.no_such_attribute


class TestBreadcrumb(APITest):
    def test_crud(self):
        breadcrumb_ssh = self.breadcrumbs.create(name=SSH_BREADCRUMB_NAME,
                                                 breadcrumb_type="ssh",
                                                 username="ssh_user",
                                                 password="ssh_pass")
        breadcrumb_ssh.update(name='renamed',
                              breadcrumb_type="ssh",
                              username="ssh_user",
                              password="ssh_pass")
        assert self.breadcrumbs.get_item(breadcrumb_ssh.id).name == 'renamed'


class TestService(APITest):
    def test_service_with_files(self):

        site_data_file = os.path.join(os.path.dirname(__file__), 'test_site.zip')

        assert len(self.client.services) == 0

        self.services.create(name=SSH_BREADCRUMB_NAME,
                             service_type="http",
                             zip_file_path=site_data_file,
                             web_apps=['phpmyadmin'],
                             https_active=False)

        assert len(self.client.services) == 1


class TestAlertPolicy(APITest):
    def test_params(self):
        assert isinstance(self.alert_policies.params(), dict)

    def test_crud(self):
        alert_policies = list(self.alert_policies)
        assert len(alert_policies) > 0
        assert all([isinstance(alert_policy, AlertPolicy) for alert_policy in alert_policies])

        rdp_policies = [alert_policy
                        for alert_policy
                        in alert_policies
                        if alert_policy.alert_type == 'rdp']

        assert len(rdp_policies) == 1

        rdp_policy = rdp_policies[0]

        assert rdp_policy.to_status == 1
        assert self.alert_policies.get_item(rdp_policy.id).to_status == 1

        rdp_policy.update_to_status(2)

        assert self.alert_policies.get_item(rdp_policy.id).to_status == 2

        self.alert_policies.reset_all_to_default()
        assert self.alert_policies.get_item(rdp_policy.id).to_status == 1


class TestConnection(APITest):

    @APITest.lab_dependent
    def test_500(self):
        with pytest.raises(ServerError):
            self.client.api_request(url='http://the-internet.herokuapp.com/status_codes/500')

    def test_cert(self):
        # With cert
        client = mazerunner.connect(
            ip_address=self.mazerunner_ip_address,
            api_key=self.api_key,
            api_secret=self.api_secret,
            certificate=self.mazerunner_certificate_path
        )
        assert len(client.deployment_groups) == 1

        # Without cert
        client = mazerunner.connect(
            ip_address=self.mazerunner_ip_address,
            api_key=self.api_key,
            api_secret=self.api_secret,
            certificate=None
        )
        assert len(client.deployment_groups) == 1


class TestEndpoints(APITest):
    @APITest.lab_dependent
    def test_deploy(self):

        def _destroy_elements():
            for cidr_mapping in self.cidr_mappings:
                cidr_mapping.delete()

            for ep in self.endpoints:
                ep.delete()

        def _are_all_tasks_complete():
            return len(self.background_tasks) == 0

        def _test_import_endpoint():

            _destroy_elements()

            assert len(self.endpoints) == 0
            assert len(self.cidr_mappings) == 0
            assert len(self.background_tasks) == 0

            cidr_mapping = self.cidr_mappings.create(
                cidr_block='%s/30' % self.lab_endpoint_ip,
                deployment_group=1,
                comments='no comments',
                active=True
            )

            assert len(self.cidr_mappings) == 1

            selected_cidr = list(self.cidr_mappings)[0]

            assert selected_cidr.cidr_block == cidr_mapping.cidr_block
            assert selected_cidr.deployment_group == cidr_mapping.deployment_group
            assert selected_cidr.comments == cidr_mapping.comments
            assert selected_cidr.active == cidr_mapping.active

            cidr_mapping.generate_endpoints()
            background_tasks = list(self.background_tasks)
            assert len(background_tasks) == 1

            wait_until(_are_all_tasks_complete, total_timeout=300)

            assert len(self.cidr_mappings) > 0
            assert len(self.endpoints) > 0

            assert len(self.endpoints.filter(keywords='no.such.thing')) == 0
            assert len(self.endpoints.filter(keywords=self.lab_endpoint_ip)) > 0

            return list(self.endpoints.filter(keywords=self.lab_endpoint_ip))[0]

        def _test_clean(ep):
            with pytest.raises(InvalidInstallMethodError):
                self.endpoints.filter(keywords=self.lab_endpoint_ip).clean_filtered(
                    install_method='invalid-install-method',
                    username=self.lab_endpoint_user,
                    password=self.lab_endpoint_password
                )

            self.endpoints.filter(keywords=self.lab_endpoint_ip).clean_filtered(
                install_method='ZIP',
                username=self.lab_endpoint_user,
                password=self.lab_endpoint_password
            )

            self.endpoints.clean_by_endpoints_ids(
                endpoints_ids=[ep.id],
                install_method='ZIP',
                username=self.lab_endpoint_user,
                password=self.lab_endpoint_password
            )

        def _test_reassignment(ep):
            dep_group = self.deployment_groups.create(name='ep1_test', description='test')

            # Assign via collection
            self.endpoints.reassign_to_group(dep_group, [ep])
            assert self.endpoints.get_item(ep.id).deployment_group.id == dep_group.id

            # Clear via collection
            self.endpoints.clear_deployment_group([ep])
            assert self.endpoints.get_item(ep.id).deployment_group is None

            # Assign via entity
            all_breadcrumbs_deployment_group = self.deployment_groups.get_item(
                self.deployment_groups.ALL_BREADCRUMBS_DEPLOYMENT_GROUP_ID)
            endpoint.reassign_to_group(all_breadcrumbs_deployment_group)
            assert self.endpoints.get_item(ep.id).deployment_group.id == \
                   all_breadcrumbs_deployment_group.id

            # Clear via entity
            ep.clear_deployment_group()
            assert self.endpoints.get_item(ep.id).deployment_group is None

            # Eventually leave the endpoint with the new deployment group assigned
            ep.reassign_to_group(dep_group)
            assert self.endpoints.get_item(ep.id).deployment_group.id == dep_group.id

        def _test_delete():
            self.endpoints.filter('no.such.endpoints').delete_filtered()
            assert len(self.endpoints.filter(self.lab_endpoint_ip)) > 0
            self.endpoints.filter(self.lab_endpoint_ip).delete_filtered()
            assert len(self.endpoints.filter(self.lab_endpoint_ip)) == 0

            _test_import_endpoint()

            endpoints = list(self.endpoints.filter(self.lab_endpoint_ip))
            assert len(endpoints) > 0
            self.endpoints.delete_by_endpoints_ids([curr_endpoint.id for curr_endpoint in endpoints])
            assert len(self.endpoints.filter(self.lab_endpoint_ip)) == 0

        def _test_data():
            _test_import_endpoint()
            csv_data = self.endpoints.export_filtered()
            pseudo_csv_file = StringIO.StringIO(csv_data)
            csv_data = csv.reader(pseudo_csv_file, delimiter=',')
            assert any([
                len(csv_line) >= 3 and csv_line[2] == self.lab_endpoint_ip
                for csv_line
                in csv_data
            ])

            assert isinstance(self.endpoints.filter_data(), dict)

        def _test_stop_import():
            _destroy_elements()

            assert len(self.background_tasks) == 0

            self.cidr_mappings.create(
                cidr_block='%s/24' % self.lab_endpoint_ip,
                deployment_group=1,
                comments='no comments',
                active=True
            )

            self.cidr_mappings.generate_all_endpoints()

            assert len(self.background_tasks) == 1
            list(self.background_tasks)[0].stop()
            assert len(self.background_tasks) == 0

            assert len(self.background_tasks.filter(running=False)) > 0
            self.background_tasks.acknowledge_all_complete()
            assert len(self.background_tasks.filter(running=False)) == 0

        endpoint = _test_import_endpoint()
        _test_clean(endpoint)
        _test_reassignment(endpoint)
        _test_delete()
        _test_data()
        _test_stop_import()

    def test_create_endpoint(self):
        for params in [
            dict(ip_address='1.1.1.1'),
            dict(dns='endpoint_address.endpoint.local'),
            dict(hostname='hostname'),
            dict(dns='endpoint_address.endpoint.local', ip_address='1.1.1.1'),
        ]:
            endpoint = self.endpoints.create(**params)
            assert endpoint
            for key, value in params.iteritems():
                assert getattr(endpoint, key) == value
            assert len(self.endpoints) == 1
            endpoint.delete()

    def test_create_endpoint_with_deployment_group(self):
        ip_address = "1.1.1.1"
        endpoint = self.endpoints.create(ip_address=ip_address, deployment_group_id=1)
        assert endpoint.ip_address == ip_address
        assert endpoint.deployment_group.name == "All Breadcrumbs"
        endpoint.delete()

    def test_create_invalid_endpoint(self):
        for params, expected_error_message in [
            (dict(ip_address='1.1.1.1.1'), "Enter a valid IPv4 address."),
            (dict(dns='A'*256), "Maximum field length is 255 characters"),
            (dict(hostname='A'*16), "Maximum field length is 15 characters"),
            (dict(), "You must provide either dns, hostname, or ip address"),
        ]:
            try:
                self.endpoints.create(**params)
                raise AssertionError, "Creation of the endpoint should raise an exception"
            except ValidationError as e:
                error = json.loads(e.message)
                if params:
                    for key in params:
                        assert key in error
                        assert error[key] == [expected_error_message]
                else:
                    assert error["non_field_errors"] == [expected_error_message]


class TestAuditLog(APITest):

    @staticmethod
    def _format_time(date_obj):
        return date_obj.strftime(ISO_TIME_FORMAT)

    def _test_time_based_queries(self):
        today = datetime.datetime.now()
        tomorrow = today + datetime.timedelta(days=1)
        a_week_ago = today + datetime.timedelta(days=-7)
        two_weeks_ago = today + datetime.timedelta(days=-14)

        # check that today has data - start date
        assert len(self.audit_log.filter(start_date=self._format_time(today))) != 0, \
            "No data from today according to start date"

        # and that tomorrow doesn't - start date
        assert len(self.audit_log.filter(start_date=self._format_time(tomorrow))) == 0, \
            "Data from tomorrow found!"

        # check that today has data - end date
        assert len(self.audit_log.filter(end_date=self._format_time(today))) != 0, \
            "No data from today according to end date"

        # and that last week doesn't - end date
        assert len(self.audit_log.filter(end_date=self._format_time(a_week_ago))) == 0, \
            "Data from a week ago found, even though we deleted everything!"

        # test time range
        assert len(self.audit_log.filter(start_date=self._format_time(a_week_ago),
                                         end_date=self._format_time(today))) != 0, \
            "No logs from the past week"

        assert len(self.audit_log.filter(start_date=self._format_time(two_weeks_ago),
                                         end_date=self._format_time(a_week_ago))) == 0, \
            "Logs found from two weeks ago."

    def _test_object_ids_queries(self, log_count):
        # get obj ids from server
        object_ids = [log_line._param_dict.get("object_ids") for log_line in self.audit_log]
        # and extract them
        object_ids = list(set([object_id[0] if object_id else None for object_id in object_ids]))

        # and make sure you have enough obj ids
        assert len(object_ids) >= 2, "No more than 1 object ID in the system"

        # test that you don't get all the alerts when filtering
        usable_object_id = [object_id for object_id in object_ids if object_id][0]

        assert len(self.audit_log.filter(object_ids=usable_object_id)) != log_count, \
            "Object ID filter returned the same amount of logs as the full filter"

    def _test_username_queries(self, log_count):
        user_id = self.client._auth.credentials['id']

        # make sure that if the username is right you get data
        assert len(self.audit_log.filter(username=[user_id])) != 0, "No logs found for the user"

        # Note: we don't have more than one user in the tests, therefore we don't
        # have a test that filters one user's info

        # check that a bad username doesnt provide any data
        bad_username = user_id * 2
        assert len(self.audit_log.filter(username=[bad_username])) == 0, \
            "Logs found for the (probably) nonexistent user {}".format(bad_username)

        # test users not list ERR
        with pytest.raises(BadParamError):
            self.audit_log.filter(username=user_id)

    def _test_category_queries(self, log_count):
        # get categories from server
        categories = list(set([log_line._param_dict.get("category") for log_line in self.audit_log]))

        # and make sure you have enough
        assert len(categories) >= 2, "No more than 1 category in the system"

        # make sure the param is OK
        assert len(self.audit_log.filter(category=[categories[0]])) != 0, \
            "No logs for previously existing filter value"

        # test that you don't get all the alerts when filtering
        assert len(self.audit_log.filter(category=[categories[0]])) != log_count, \
            "Filtered list returned the same amount of logs as the full filter"

        # test categories not list ERR
        with pytest.raises(BadParamError):
            self.audit_log.filter(category=categories[0])

    def _test_event_type_queries(self, log_count):
        # get event_types from server
        event_types = list(set([log_line._param_dict.get("event_type_label") for log_line in self.audit_log]))

        # and make sure you have enough
        assert len(event_types) >= 2, "No more than 1 event type in the system."

        # make sure the param is OK
        assert len(self.audit_log.filter(event_type=[event_types[0]])) != 0, \
            "No logs for previously existing filter value"

        # test that you don't get all the alerts when filtering
        assert len(self.audit_log.filter(event_type=[event_types[0]])) != log_count, \
            "Filtered list returned the same amount of logs as the full filter"

        # test event type not list ERR
        with pytest.raises(BadParamError):
            self.audit_log.filter(event_type=event_types[0])

    def test_audit_log_query(self):

        # test delete (at the start for a clean log)
        self.audit_log.delete()
        logger.info("Audit log cleared")

        # build all sorts of logs
        decoy_ssh = self.create_decoy(dict(name=SSH_DECOY_NAME,
                                           hostname="decoyssh",
                                           os="Ubuntu_1404",
                                           vm_type="KVM"))

        # test query
        log_count = self.audit_log
        assert len(log_count) != 0, "No logs found"
        assert type(list(self.audit_log)[0]) == AuditLogLine, "Invalid output"

        self._test_time_based_queries()
        self._test_object_ids_queries(log_count)
        self._test_username_queries(log_count)
        self._test_category_queries(log_count)
        self._test_event_type_queries(log_count)

        # test filter=False with params
        assert len(self.audit_log.filter(event_type=["Delete"], filter_enabled=False)) == \
               len(self.audit_log.filter(event_type=["Action"], filter_enabled=False)), \
            "filter_enabled = False should make other filters redundant"

        # test delete (again to make sure the log is actually cleaned)
        self.audit_log.delete()
        assert len(self.audit_log) != 0, "No delete log!"
        assert len(self.audit_log) == 1, "Other logs found"

    # once this issue is fixed we need to use the provided data from the decoy creation to actually filter items
    @pytest.mark.xfail(reason="Item filtering is broken on server side")
    def test_audit_log_item_filter(self):
        # look for an item that doesnt exist
        INVALID_ITEM_FILTER = "qweasdzxc"
        assert len(self.audit_log.filter(item=INVALID_ITEM_FILTER)) == 0
