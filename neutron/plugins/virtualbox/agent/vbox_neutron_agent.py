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

import platform
import re
import sys
import time

import eventlet
if sys.platform == 'win32':
    # eventlet.monkey_patch() breaks subprocess.Popen on Windows
    eventlet.monkey_patch(os=False)
else:
    eventlet.monkey_patch()

from oslo_config import cfg
import oslo_messaging

from neutron.agent.common import config
from neutron.agent import rpc as agent_rpc
from neutron.agent import securitygroups_rpc as sg_rpc
from neutron.common import config as common_config
from neutron.common import constants as n_const
from neutron.common import topics
from neutron import context as n_context
from neutron import i18n
from neutron.openstack.common import log as logging
from neutron.openstack.common import loopingcall
from neutron.plugins.common import constants as p_const
from neutron.plugins.virtualbox.common import constants
from neutron.plugins.virtualbox.common import exception as vbox_exc
from neutron.plugins.virtualbox.common import vboxapi

LOG = logging.getLogger(__name__)
AGENT_OPS = [
    cfg.ListOpt('physical_network_mappings',
                default=[],
                help=i18n._('List of <physical_network>:<interface> where '
                            'the physical networks can be expressed with '
                            'wildcards, e.g.: ."*:eth1"')),

    cfg.StrOpt('local_network',
               default='intnet',
               help=i18n._('Private network name used for local networks.')),

    cfg.IntOpt('polling_interval', default=2,
               help=i18n._('The number of seconds the agent will wait between '
                           'polling for local device changes.')),
]
CONF = cfg.CONF
CONF.register_opts(AGENT_OPS, 'AGENT')
config.register_agent_state_opts_helper(cfg.CONF)


class VBoxSecurityCallbackMixin(sg_rpc.SecurityGroupAgentRpcCallbackMixin):

    target = oslo_messaging.Target(version=constants.RPC_VERSION)

    def __init__(self, sg_agent):
        super(VBoxSecurityCallbackMixin, self).__init__()
        self.sg_agent = sg_agent


class VBoxSecurityAgent(sg_rpc.SecurityGroupAgentRpc):

    target = oslo_messaging.Target(version=constants.RPC_VERSION)

    def __init__(self, context, plugin_rpc):
        super(VBoxSecurityAgent, self).__init__(context, plugin_rpc)
        if sg_rpc.is_firewall_enabled():
            self._setup_rpc()

    @property
    def use_enhanced_rpc(self):
        return False

    def _setup_rpc(self):
        self.topic = topics.AGENT
        self.endpoints = [VBoxSecurityCallbackMixin(self)]
        consumers = [[topics.SECURITY_GROUP, topics.UPDATE]]

        self.connection = agent_rpc.create_consumers(self.endpoints,
                                                     self.topic,
                                                     consumers)


class VBoxNeutronAgent(object):

    target = oslo_messaging.Target(version=constants.RPC_VERSION)

    def __init__(self):
        super(VBoxNeutronAgent, self).__init__()
        self.agend_id = None
        self.connection = None
        self.context = None
        self.endpoints = None
        self.topic = None
        self.plugin_rpc = None
        self.sec_groups_agent = None
        self.state_rpc = None
        self._network_manager = vboxapi.VBoxNetworkManage()
        self._ignore_list = {}
        self._network_map = {}
        self._physical_network_mappings = {}
        self._polling_interval = CONF.AGENT.polling_interval

        self._load_physical_network_mappings()
        self._setup_rpc()

    def _load_physical_network_mappings(self):
        for mapping in CONF.AGENT.physical_network_mappings:
            parts = mapping.split(':')
            if len(parts) != 2:
                LOG.debug('Invalid physical network mapping: %s', mapping)
                continue
            pattern = re.escape(parts[0].strip()).replace('\\*', '.*')
            network = parts[1].strip()
            self._physical_network_mappings[pattern] = network

    def _setup_rpc(self):
        self.agent_id = 'vbox_%s' % platform.node()
        self.topic = topics.AGENT
        self.plugin_rpc = agent_rpc.PluginApi(topics.PLUGIN)
        self.state_rpc = agent_rpc.PluginReportStateAPI(topics.PLUGIN)
        # RPC network init
        self.context = n_context.get_admin_context_without_session()
        # Handle updates from service
        self.endpoints = [self]
        # Define the listening consumers for the agent
        consumers = [[topics.PORT, topics.UPDATE],
                     [topics.NETWORK, topics.DELETE],
                     [topics.PORT, topics.DELETE],
                     [constants.TUNNEL, topics.UPDATE]]
        self.connection = agent_rpc.create_consumers(self.endpoints,
                                                     self.topic,
                                                     consumers)
        self.sec_groups_agent = VBoxSecurityAgent(
            self.context, self.plugin_rpc)

        report_interval = CONF.AGENT.report_interval
        if report_interval:
            heartbeat = loopingcall.FixedIntervalLoopingCall(
                self._report_state)
            heartbeat.start(interval=report_interval)

        self.agent_state = {
            'binary': 'neutron-vbox-agent',
            'host': cfg.CONF.host,
            'topic': n_const.L2_AGENT_TOPIC,
            'configurations': {
                'network_mappings': self._physical_network_mappings
            },
            'agent_type': n_const.AGENT_TYPE_VBOX,
            'start_flag': True
        }

    def _report_state(self):
        try:
            self.state_rpc.report_state(self.context,
                                        self.agent_state)
            self.agent_state.pop('start_flag', None)
        except Exception:
            LOG.exception(i18n._LE("Failed reporting state!"))

    def _device_info_has_changes(self, device_info):
        return (device_info.get('added') or device_info.get('removed'))

    def _get_current_devices(self):
        self._network_manager.refresh()
        return self._network_manager.devices()

    def _get_interface(self, phys_network_name):
        for pattern in self._physical_network_mappings:
            if phys_network_name is None:
                phys_network_name = ''
            if re.match(pattern, phys_network_name):
                return self._physical_network_mappings[pattern]

        # Not found in the mappings
        return phys_network_name

    def _get_interface_name(self, network_type, physical_network):
        if network_type != p_const.TYPE_LOCAL:
            interface_name = self._get_interface(physical_network)
        else:
            interface_name = CONF.AGENT.local_network
        return interface_name

    def _add_device(self, device_details):
        if 'port_id' not in device_details:
            LOG.debug("The `port_id` is not provided for this device.")
            return False

        if not device_details['network_type'] == p_const.TYPE_FLAT:
            LOG.error(i18n._LE('Unsupported network type %s'),
                      device_details['network_type'])
            return False

        if not self._network_manager.device_exists(device_details['port_id']):
            LOG.warning(i18n._LW("No port %(port_id)s defined on agent."),
                        {"port_id": device_details['port_id']})
            return False

        self._network_manager.setup_device(
            device_details['port_id'],
            self._get_interface_name(
                    device_details['network_type'],
                    device_details['physical_network']))
        return True

    def treat_devices_added(self, devices):
        LOG.debug("Treat devices %(devices)s added.", {"devices": devices})
        sync_required = False
        try:
            devices_details_list = self.plugin_rpc.get_devices_details_list(
                self.context, devices, self.agent_id)
        except Exception as exc:
            LOG.debug(
                "Unable to get ports details for devices %(devices)s: %(exc)s",
                {'devices': devices, 'exc': exc})
            return True     # resync is needed

        for device_details in devices_details_list:
            LOG.debug("Treat device: %(device)s", {"device": device_details})
            device = device_details['device']
            try:
                if self._add_device(device_details):
                    LOG.info(i18n._LI(
                        "Port %(device)s updated. Details: %(details)s"),
                        {'device': device, 'details': device_details})
            except vbox_exc.VBoxManageError as error:
                LOG.error(i18n._LE("Fail to bind port: %(port)s: %(error)s"),
                          {"port": device_details['port_id'], "error": error})
                sync_required = True
            self.plugin_rpc.update_device_up(
                        self.context, device, self.agent_id, cfg.CONF.host)
        return sync_required

    def treat_devices_removed(self, devices):
        LOG.debug("Treat devices %(devices)s removed", {"devices": devices})
        sync_required = False
        for device in devices:
            LOG.info(i18n._LI("Removing port %s"), device)
            try:
                self.plugin_rpc.update_device_down(
                    self.context, device, self.agent_id,
                    cfg.CONF.host)
            except Exception as error:
                LOG.debug("Removing port failed for device %(device)s:"
                          " %(error)s",
                          {"device": device, "error": error})
                sync_required = True
                continue

        return sync_required

    def process_network_devices(self, device_info):
        resync_removed = False
        resync_added = False

        if device_info.get('added'):
            resync_removed = self.treat_devices_added(device_info.get('added'))

        if device_info.get('removed'):
            resync_added = self.treat_devices_removed(device_info['removed'])

        # If one of the above operations fails => resync with plugin
        return resync_removed or resync_added

    def scan_devices(self, previous, sync):
        device_info = {}
        current_devices = self._get_current_devices()
        device_info['current'] = current_devices

        if previous is None:
            # This is the first iteration of daemon_loop().
            previous = {'added': set(), 'current': set(), 'removed': set()}

        if sync:
            # This is the first iteration, or the previous one had a problem.
            # Re-add all existing devices.
            device_info['added'] = current_devices

            # Retry cleaning devices that may not have been cleaned properly.
            # And clean any that disappeared since the previous iteration.
            device_info['removed'] = (previous['removed'] | previous['current']
                                      - current_devices)

        else:
            device_info['added'] = current_devices - previous['current']
            device_info['removed'] = previous['current'] - current_devices

        return device_info

    def daemon_loop(self):
        LOG.info(i18n._LI("VBox Agent RPC Daemon Started!"))
        device_info = None
        sync = True

        while True:
            start = time.time()
            device_info = self.scan_devices(previous=device_info, sync=sync)

            if sync:
                LOG.info(i18n._LI("Agent out of sync with plugin!"))
                sync = False

            if self._device_info_has_changes(device_info):
                LOG.debug("Agent loop found changes! %s", device_info)
                try:
                    sync = self.process_network_devices(device_info)
                except vbox_exc.VBoxException as error:
                    LOG.exception(
                        i18n._LE("Error: `%(error)s` in agent loop."
                                 " Devices info: %(device)s"),
                        {"error": error, "device": device_info})
                    sync = True

            # sleep till end of polling interval
            elapsed = (time.time() - start)
            if elapsed < self._polling_interval:
                time.sleep(self._polling_interval - elapsed)
            else:
                LOG.debug("Loop iteration exceeded interval "
                          "(%(polling_interval)s vs. %(elapsed)s)!",
                          {'polling_interval': self._polling_interval,
                           'elapsed': elapsed})


def main():
    common_config.init(sys.argv[1:])
    common_config.setup_logging()

    plugin = VBoxNeutronAgent()

    # Start everything.
    LOG.info(i18n._LI("Agent initialized successfully, now running... "))
    plugin.daemon_loop()

if __name__ == "__main__":
    main()
