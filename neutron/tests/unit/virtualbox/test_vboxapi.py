# Copyright (c) 2015 Cloudbase Solutions Srl
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Unit tests for the VirtualBox API.
"""

import subprocess

import mock
from oslo.config import cfg

from neutron.plugins.virtualbox.common import constants
from neutron.plugins.virtualbox.common import exception as vbox_exc
from neutron.plugins.virtualbox.common import vboxapi
from neutron.tests import base


class TestVBoxManage(base.BaseTestCase):

    _FAKE_STDERR = 'fake-error'
    _RETRY_COUNT = 3

    def setUp(self):
        super(TestVBoxManage, self).setUp()
        cfg.CONF.set_default('retry_count', self._RETRY_COUNT,
                             group="virtualbox")
        cfg.CONF.set_default('retry_interval', 0, group="virtualbox")

        self._instance = "fake-instance"
        self._vbox_manage = vboxapi.VBoxManage()

    @mock.patch('subprocess.Popen')
    def test_execute(self, mock_popen):
        mock_communicate = mock_popen().communicate
        mock_communicate.return_value = (mock.sentinel.stdout, None)

        mock_popen.side_effect = [
            # 1. The command was successfuly executed
            mock_popen(),
            # 2. The command returns an error message
            subprocess.CalledProcessError(1, "", self._FAKE_STDERR)
        ]

        self.assertEqual((mock.sentinel.stdout, None),
                         self._vbox_manage._execute('command'))
        self.assertEqual((None, self._FAKE_STDERR),
                         self._vbox_manage._execute('command'))

    @mock.patch('subprocess.Popen')
    def test_execute_retry(self, mock_popen):
        mock_process = mock.Mock()
        mock_communicate = mock_process.communicate
        mock_popen.side_effect = [mock_process] * self._RETRY_COUNT
        mock_communicate.side_effect = [
            (None, constants.VBOX_E_ACCESSDENIED)] * self._RETRY_COUNT

        self._vbox_manage._execute('command')
        self.assertEqual(self._RETRY_COUNT, mock_popen.call_count)
        self.assertEqual(self._RETRY_COUNT, mock_communicate.call_count)

    @mock.patch('neutron.plugins.virtualbox.common.vboxapi.VBoxManage'
                '._execute')
    def test_list(self, mock_execute):
        stdout, stderr = mock.sentinel.stdout, mock.sentinel.stderr
        mock_execute.side_effect = [(stdout, stderr), (stdout, None)]
        self.assertRaises(vbox_exc.VBoxManageError, self._vbox_manage.list,
                          mock.sentinel.info)
        self.assertEqual(stdout, self._vbox_manage.list(mock.sentinel.info))

    @mock.patch('neutron.plugins.virtualbox.common.vboxapi.VBoxManage'
                '._execute')
    def test_show_vm_info(self, mock_execute):
        mock_execute.side_effect = [
            ('"a"="b"', None), ('\n"a"="b"\n', None), ('"a" = "b"', None),
            ('"none"="none"', None)
        ]

        for _ in range(3):
            response = self._vbox_manage.show_vm_info(self._instance)
            self.assertEqual({'a': 'b'}, response)

        response = self._vbox_manage.show_vm_info(self._instance)
        self.assertIsNone(response["none"])

    @mock.patch('neutron.plugins.virtualbox.common.vboxapi.VBoxManage'
                '._execute')
    def test_show_vm_info_fail(self, mock_execute):
        mock_execute.side_effect = [(None, self._FAKE_STDERR),
                                    ('invalid', None)]

        self.assertRaises(vbox_exc.VBoxManageError,
                          self._vbox_manage.show_vm_info,
                          self._instance)
        self.assertEqual({}, self._vbox_manage.show_vm_info(self._instance))

    @mock.patch('neutron.plugins.virtualbox.common.vboxapi.VBoxManage'
                '._execute')
    def test_modify_network(self, mock_execute):
        mock_execute.return_value = [None, None]
        self._vbox_manage.modify_network(
            self._instance, 1, [(constants.FIELD_NIC, mock.sentinel.value)])

        mock_execute.assert_called_once_with(
            self._vbox_manage.MODIFY_VM, self._instance,
            constants.FIELD_NIC % {"index": 1},
            mock.sentinel.value)

    @mock.patch('neutron.plugins.virtualbox.common.vboxapi.VBoxManage'
                '._execute')
    def test_update_network(self, mock_execute):
        mock_execute.return_value = [None, None]
        self._vbox_manage.update_network(
            self._instance, 1, constants.FIELD_NIC, [mock.sentinel.value])

        mock_execute.assert_called_once_with(
            self._vbox_manage.CONTROL_VM, self._instance,
            constants.FIELD_NIC % {"index": 1},
            mock.sentinel.value)


class TestVBoxNetworkManage(base.BaseTestCase):

    def setUp(self):
        super(TestVBoxNetworkManage, self).setUp()
        cfg.CONF.set_default('nic_type', mock.sentinel.nic_type,
                             group="virtualbox")
        self._instance = "fake-instance"
        self._network = vboxapi.VBoxNetworkManage()

    @mock.patch('neutron.plugins.virtualbox.common.vboxapi.VBoxManage'
                '.list')
    def test_instances(self, mock_list):
        mock_list.return_value = ('"instance_name" {instance_uuid}\n'
                                  'invalid_line\n')
        response = list(self._network._instances())

        mock_list.assert_called_once_with(constants.VMS_INFO)
        self.assertEqual(["instance_name"], response)

    @mock.patch('oslo_serialization.jsonutils.loads')
    def test_process_description(self, mock_loads):
        mock_loads.return_value = {
            'network': {mock.sentinel.device: mock.sentinel.mac_address}
        }
        self._network._process_description(mock.sentinel.description)

        mock_loads.assert_called_once_with(mock.sentinel.description)
        self.assertTrue(mock.sentinel.device in
                        self._network._device_map)
        self.assertEqual(mock.sentinel.mac_address,
                         self._network._device_map[mock.sentinel.device])

    @mock.patch('oslo_serialization.jsonutils.loads')
    def test_process_description_fail(self, mock_loads):
        mock_loads.side_effect = [{}, ValueError()]

        for _ in range(2):
            self.assertFalse(self._network._process_description(
                mock.sentinel.description))
        self.assertFalse(self._network._process_description(None))

    @mock.patch('neutron.plugins.virtualbox.common.vboxapi.VBoxNetworkManage'
                '._process_description')
    @mock.patch('neutron.plugins.virtualbox.common.vboxapi.VBoxManage'
                '.show_vm_info')
    def test_inspect_instance(self, mock_vm_info, mock_process_desc):
        index = "1"
        expected_nic = {
            mock.sentinel.device: {
                "index": index,
                "instance": self._instance,
                "state": mock.sentinel.power_state,
                constants.MAC_ADDRESS: mock.sentinel.address,
                constants.NIC_MODE: mock.sentinel.nic_mode,
            }
        }
        mock_vm_info.return_value = {
            constants.VM_STATE: mock.sentinel.power_state,
            constants.VM_DESCRIPTION: mock.sentinel.description,
            constants.NIC_MODE + index: mock.sentinel.nic_mode,
            constants.MAC_ADDRESS + index: mock.sentinel.address,
        }
        self._network._device_map[mock.sentinel.address] = mock.sentinel.device

        self._network._inspect_instance(self._instance)

        mock_vm_info.assert_called_once_with(self._instance)
        mock_process_desc.assert_called_once_with(mock.sentinel.description)
        self.assertTrue(mock.sentinel.device in self._network._nic)
        self.assertEqual(expected_nic, self._network._nic)

    @mock.patch('neutron.plugins.virtualbox.common.vboxapi.VBoxNetworkManage'
                '._process_description')
    @mock.patch('neutron.plugins.virtualbox.common.vboxapi.VBoxManage'
            '.show_vm_info')
    def test_inspect_instance_fail(self, mock_vm_info, mock_process_desc):
        mock_vm_info.side_effect = [
            vbox_exc.InstanceNotFound(instance=self._instance),
            {}
        ]
        mock_process_desc.return_value = False

        for _ in range(2):
            self.assertIsNone(self._network._inspect_instance(self._instance))

    @mock.patch('neutron.plugins.virtualbox.common.vboxapi.VBoxNetworkManage'
                '._inspect_instance')
    @mock.patch('neutron.plugins.virtualbox.common.vboxapi.VBoxNetworkManage'
                '._instances')
    def test_refresh(self, mock_instances, mock_inspect):
        mock_instances.return_value = iter([mock.sentinel.instance])
        self._network.refresh()

        mock_inspect.assert_called_once_with(mock.sentinel.instance)

    def test_device_exists(self):
        self._network._nic[mock.sentinel.device_id] = None

        self.assertTrue(self._network.device_exists(mock.sentinel.device_id))
        self.assertFalse(self._network.device_exists(mock.sentinel.device_id2))

    def test_devices(self):
        self._network._nic = {
            mock.sentinel.device_id: None,
            mock.sentinel.device_id2: None
        }

        self.assertEqual({mock.sentinel.device_id, mock.sentinel.device_id2},
                         self._network.devices())

    @mock.patch('neutron.plugins.virtualbox.common.vboxapi.VBoxManage'
                '.modify_network')
    def test_modify_network(self, mock_modify_network):
        self._network._local_network = False
        device = {
            "instance": self._instance,
            "index": mock.sentinel.index
        }

        self._network._modify_network(device, mock.sentinel.network)
        mock_modify_network.assert_called_once_with(
            self._instance, mock.sentinel.index,
            [
                (constants.FIELD_NIC_TYPE, mock.sentinel.nic_type),
                (constants.FIELD_NIC_MODE, constants.NIC_MODE_BRIDGED),
                (constants.FIELD_BRIDGE_ADAPTER, mock.sentinel.network),
                (constants.FIELD_CABLE_CONNECTED, constants.ON)
            ]
        )

    @mock.patch('neutron.plugins.virtualbox.common.vboxapi.VBoxManage'
                '.modify_network')
    def test_modify_network_local(self, mock_modify_network):
        self._network._local_network = True
        device = {
            "instance": self._instance,
            "index": mock.sentinel.index
        }

        self._network._modify_network(device, mock.sentinel.network)
        mock_modify_network.assert_called_once_with(
            self._instance, mock.sentinel.index,
            [
                (constants.FIELD_NIC_TYPE, mock.sentinel.nic_type),
                (constants.FIELD_NIC_MODE, constants.NIC_MODE_HOSTONLY),
                (constants.FIELD_HOSTONLY_ADAPTER, mock.sentinel.network),
                (constants.FIELD_CABLE_CONNECTED, constants.ON)
            ]
        )

    @mock.patch('neutron.plugins.virtualbox.common.vboxapi.VBoxManage'
                '.update_network')
    def test_update_network(self, mock_update_network):
        self._network._local_network = False
        device = {
            "instance": self._instance,
            "index": mock.sentinel.index
        }

        self._network._update_network(device, mock.sentinel.network)

        mock_update_network.assert_has_calls([
            mock.call(
                instance=self._instance, index=mock.sentinel.index,
                field=constants.FIELD_NIC,
                value=(constants.NIC_MODE_BRIDGED, mock.sentinel.network)
            ),
            mock.call(
                instance=self._instance, index=mock.sentinel.index,
                field=constants.FIELD_LINK_STATE,
                value=(constants.ON,)
            )
        ])

    @mock.patch('neutron.plugins.virtualbox.common.vboxapi.VBoxManage'
                '.update_network')
    def test_update_network_local(self, mock_update_network):
        self._network._local_network = True
        device = {
            "instance": self._instance,
            "index": mock.sentinel.index
        }

        self._network._update_network(device, mock.sentinel.network)

        mock_update_network.assert_has_calls([
            mock.call(
                instance=self._instance, index=mock.sentinel.index,
                field=constants.FIELD_NIC,
                value=(constants.NIC_MODE_HOSTONLY, mock.sentinel.network)
            ),
            mock.call(
                instance=self._instance, index=mock.sentinel.index,
                field=constants.FIELD_LINK_STATE,
                value=(constants.ON,)
            )
        ])

    @mock.patch('neutron.plugins.virtualbox.common.vboxapi.VBoxNetworkManage'
                '._modify_network')
    @mock.patch('neutron.plugins.virtualbox.common.vboxapi.VBoxNetworkManage'
                '._update_network')
    def test_setup_device(self, mock_update_network, mock_modify_network):
        device = {"state": constants.POWER_OFF}
        self._network._nic[mock.sentinel.device] = device

        self._network.setup_device(mock.sentinel.device,
                                   mock.sentinel.network)

        mock_modify_network.assert_called_once_with(
            device, mock.sentinel.network)
        self.assertEqual(0, mock_update_network.call_count)

    @mock.patch('neutron.plugins.virtualbox.common.vboxapi.VBoxNetworkManage'
                '._modify_network')
    @mock.patch('neutron.plugins.virtualbox.common.vboxapi.VBoxNetworkManage'
                '._update_network')
    def test_setup_device_update(self, mock_update_network,
                                 mock_modify_network):
        device = {"state": constants.POWER_OFF}
        mock_modify_network.side_effect = [
            vbox_exc.VBoxManageError(method=None, reason="error")]
        self._network._nic[mock.sentinel.device] = device

        self._network.setup_device(mock.sentinel.device,
                                   mock.sentinel.network)

        mock_modify_network.assert_called_once_with(
            device, mock.sentinel.network)
        mock_update_network.assert_called_once_with(
            device, mock.sentinel.network)

    @mock.patch('neutron.plugins.virtualbox.common.vboxapi.VBoxNetworkManage'
                '._modify_network')
    @mock.patch('neutron.plugins.virtualbox.common.vboxapi.VBoxNetworkManage'
                '._update_network')
    def test_setup_device_fail(self, mock_update_network,
                               mock_modify_network):
        self._network.setup_device(mock.sentinel.device,
                                   mock.sentinel.network)

        self.assertEqual(0, mock_modify_network.call_count)
        self.assertEqual(0, mock_update_network.call_count)
