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
Unit tests for VirtualBox Neutron agent
"""

import mock
from oslo.config import cfg

from neutron.common import constants as n_const
from neutron.plugins.common import constants as p_const
from neutron.plugins.virtualbox.common import exception as vbox_exc
from neutron.plugins.virtualbox.agent import vbox_neutron_agent
from neutron.tests import base


class TestVBoxNeutronAgent(base.BaseTestCase):

    _FAKE_PORT_ID = 'fake_port_id'

    def setUp(self):
        super(TestVBoxNeutronAgent, self).setUp()

        class MockFixedIntervalLoopingCall(object):
            def __init__(self, f):
                self.f = f

            def start(self, interval=0):
                self.f()

        fake_agent_state = {
            'binary': 'neutron-vbox-agent',
            'host': 'fake_host_name',
            'topic': 'N/A',
            'configurations': {'network_mappings': ['*:eth1']},
            'agent_type': n_const.AGENT_TYPE_VBOX,
            'start_flag': True
        }

        mock.patch('neutron.openstack.common.loopingcall.'
                   'FixedIntervalLoopingCall',
                   new=MockFixedIntervalLoopingCall).start()

        # disable setting up periodic state reporting
        cfg.CONF.set_override('report_interval', 0, 'AGENT')
        cfg.CONF.set_default('firewall_driver',
                             'neutron.agent.firewall.NoopFirewallDriver',
                             group='SECURITYGROUP')

        with mock.patch('neutron.plugins.virtualbox.agent.vbox_neutron_agent'
                        '.VBoxNeutronAgent._setup_rpc'):
            self.agent = vbox_neutron_agent.VBoxNeutronAgent()

        self.agent.plugin_rpc = mock.Mock()
        self.agent.sec_groups_agent = mock.MagicMock()
        self.agent.context = mock.Mock()
        self.agent.agent_id = mock.Mock()
        self.agent.agent_state = fake_agent_state

    @mock.patch('neutron.plugins.virtualbox.common.vboxapi.VBoxNetworkManage'
                '.devices')
    @mock.patch('neutron.plugins.virtualbox.common.vboxapi.VBoxNetworkManage'
                '.refresh')
    def test_get_current_devices(self, mock_network_refresh,
                                 mock_network_devices):
        mock_network_devices.return_value = mock.sentinel.devices
        devices = self.agent._get_current_devices()

        mock_network_devices.assert_called_once_with()
        mock_network_devices.assert_called_once_with()
        self.assertEqual(mock.sentinel.devices, devices)

    @mock.patch('neutron.plugins.virtualbox.common.vboxapi.VBoxNetworkManage'
                '.setup_device')
    @mock.patch('neutron.plugins.virtualbox.agent.vbox_neutron_agent'
                '.VBoxNeutronAgent._get_interface_name')
    @mock.patch('neutron.plugins.virtualbox.common.vboxapi.VBoxNetworkManage'
                '.device_exists')
    def test_add_device(self, mock_device_exists, mock_if_name,
                        mock_setup_device):
        mock_device_exists.return_value = True
        mock_if_name.return_value = mock.sentinel.if_name
        device_info = {
            "port_id": mock.sentinel.port_id,
            "network_type": p_const.TYPE_FLAT,
            "physical_network": mock.sentinel.network
        }
        status = self.agent._add_device(device_info)

        mock_device_exists.assert_called_once_with(mock.sentinel.port_id)
        mock_if_name.assert_called_once_with(p_const.TYPE_FLAT,
                                             mock.sentinel.network)
        mock_setup_device.assert_called_once_with(mock.sentinel.port_id,
                                                  mock.sentinel.if_name)
        self.assertTrue(status)

    @mock.patch('neutron.plugins.virtualbox.common.vboxapi.VBoxNetworkManage'
                '.device_exists')
    def test_add_device_fail(self, mock_device_exists):
        mock_device_exists.return_value = False
        device_details = [
            # 1. Missing port id
            {},
            # 2. Unsupported network type
            {
                "port_id": mock.sentinel.port_id,
                "network_type": mock.sentinel.network
            },
            # 3. The port is not defined to agent
            {
                "port_id": mock.sentinel.port_id,
                "network_type": p_const.TYPE_FLAT
            },
        ]

        for device in device_details:
            self.assertFalse(self.agent._add_device(device))
        mock_device_exists.assert_called_once_with(mock.sentinel.port_id)

    @mock.patch('neutron.plugins.virtualbox.agent.vbox_neutron_agent'
                '.VBoxNeutronAgent._add_device')
    def test_treat_devices_added(self, mock_add_device):
        devices = [{"device": mock.sentinel.device}]
        attrs = {'get_devices_details_list.return_value': devices}
        self.agent.plugin_rpc.configure_mock(**attrs)

        with mock.patch.object(self.agent.plugin_rpc,
                               "update_device_up") as mock_device_up:
            sync_required = self.agent.treat_devices_added(
                mock.sentinel.devices)

            mock_add_device.assert_called_once_with(devices[0])
            self.assertFalse(sync_required)
            self.assertTrue(mock_device_up.called)

    @mock.patch('neutron.plugins.virtualbox.agent.vbox_neutron_agent'
                '.VBoxNeutronAgent._add_device')
    def test_treat_devices_added_binding_failed(self, mock_add_device):
        devices = [{"device": mock.sentinel.device,
                    "port_id": mock.sentinel.port_id}]
        attrs = {'get_devices_details_list.return_value': devices}
        self.agent.plugin_rpc.configure_mock(**attrs)
        mock_add_device.side_effect = [
            vbox_exc.VBoxManageError(method=None, reason=None)
        ]

        with mock.patch.object(self.agent.plugin_rpc,
                               "update_device_up") as mock_device_up:
            sync_required = self.agent.treat_devices_added(
                mock.sentinel.devices)

            mock_add_device.assert_called_once_with(devices[0])
            self.assertTrue(sync_required)
            self.assertFalse(mock_device_up.called)

    def test_treat_devices_added_returns_true_for_missing_device(self):
        attrs = {'get_devices_details_list.side_effect': Exception()}
        self.agent.plugin_rpc.configure_mock(**attrs)
        self.assertTrue(self.agent.treat_devices_added(mock.sentinel.devices))

    def test_treat_devices_removed(self):
        sync = self.agent.treat_devices_removed([mock.sentinel.device])

        self.agent.plugin_rpc.update_device_down.assert_called_once_with(
            self.agent.context, mock.sentinel.device, self.agent.agent_id,
            cfg.CONF.host
        )
        self.assertFalse(sync)

    def test_treat_devices_removed_fail(self):
        self.agent.plugin_rpc.update_device_down.side_effect = [Exception]
        sync = self.agent.treat_devices_removed([mock.sentinel.device])

        self.agent.plugin_rpc.update_device_down.assert_called_once_with(
            self.agent.context, mock.sentinel.device, self.agent.agent_id,
            cfg.CONF.host
        )
        self.assertTrue(sync)

    @mock.patch('neutron.plugins.virtualbox.agent.vbox_neutron_agent'
                '.VBoxNeutronAgent.treat_devices_added')
    @mock.patch('neutron.plugins.virtualbox.agent.vbox_neutron_agent'
                '.VBoxNeutronAgent.treat_devices_removed')
    def process_network_devices(self, mock_devices_added,
                                mock_devices_removed):
        mock_devices_added.side_effect = [True, True, False]
        mock_devices_removed.side_effect = [True, False, False]

    def _test_scan_devices(self, previous, fake_current,
                           expected, sync):

        self.agent._get_current_devices = mock.Mock()
        self.agent._get_current_devices.return_value = fake_current
        results = self.agent.scan_devices(previous, sync)
        self.assertEqual(expected, results)

    def test_scan_devices_no_changes(self):
        previous = {
            'current': {mock.sentinel.device1, mock.sentinel.device2},
            'added': set(),
            'removed': set()
        }
        fake_current = {mock.sentinel.device1, mock.sentinel.device2}
        expected = {
            'current': {mock.sentinel.device1, mock.sentinel.device2},
            'added': set(),
            'removed': set()
        }
        self._test_scan_devices(previous, fake_current, expected, sync=False)

    def test_scan_devices_added_removed(self):
        previous = {
            'current': {mock.sentinel.device1, mock.sentinel.device2},
            'added': set(),
            'removed': set()
        }
        fake_current = {mock.sentinel.device2, mock.sentinel.device3}
        expected = {
            'current': {mock.sentinel.device2, mock.sentinel.device3},
            'added': {mock.sentinel.device3, },
            'removed': {mock.sentinel.device1, }
        }
        self._test_scan_devices(previous, fake_current, expected, sync=False)

    def test_scan_devices_removed_retried_on_sync(self):
        previous = {
            'current': {mock.sentinel.device2, mock.sentinel.device3},
            'added': set(),
            'removed': {mock.sentinel.device1, }
        }
        fake_current = {mock.sentinel.device2, mock.sentinel.device3}
        expected = {
            'current': {mock.sentinel.device2, mock.sentinel.device3},
            'added': {mock.sentinel.device2, mock.sentinel.device3},
            'removed': {mock.sentinel.device1, }
        }
        self._test_scan_devices(previous, fake_current, expected, sync=True)

    def test_scan_devices_vanished_removed_on_sync(self):
        previous = {
            'current': {mock.sentinel.device2, mock.sentinel.device3},
            'added': set(),
            'removed': {mock.sentinel.device1, }
        }
        # mock.sentinel.device2 disappeared.
        fake_current = {mock.sentinel.device3, }
        expected = {
            'current': {mock.sentinel.device3, },
            'added': {mock.sentinel.device3, },
            'removed': {mock.sentinel.device1, mock.sentinel.device2}
        }
        self._test_scan_devices(previous, fake_current, expected,
                                sync=True)
