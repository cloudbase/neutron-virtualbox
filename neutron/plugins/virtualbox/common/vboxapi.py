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
A connection to VirtualBox via VBoxManage.
"""

import subprocess
import time

from oslo_config import cfg
from oslo_serialization import jsonutils

from neutron.i18n import _LW
from neutron.openstack.common import log as logging
from neutron.plugins.virtualbox.common import constants
from neutron.plugins.virtualbox.common import exception

LOG = logging.getLogger(__name__)
VIRTUAL_BOX = [
    cfg.IntOpt('retry_count',
               default=3,
               help='The number of times to retry to execute command.'),
    cfg.IntOpt('retry_interval',
               default=1,
               help='Interval between execute attempts, in seconds'),
    cfg.StrOpt('vboxmanage_cmd',
               default="VBoxManage",
               help='Path of VBoxManage command which is used comunicate'
                    ' with the VirtualBox.'),
    cfg.StrOpt('nic_type',
               default='82540EM',        # Intel PRO/1000 MT Desktop
               help='The network hardware which VirtualBox presents to '
                    'the guest.'),
    cfg.BoolOpt('use_local_network',
                default=False,
                help='Use host-only network instead of bridge.')
]

CONF = cfg.CONF
CONF.register_opts(VIRTUAL_BOX, 'virtualbox')


class VBoxManage(object):

    """Wrapper over VBoxManage command line tool."""

    CONTROL_VM = 'controlvm'
    LIST = 'list'
    SHOW_VM_INFO = 'showvminfo'
    MODIFY_VM = 'modifyvm'

    @classmethod
    def _execute(cls, *args):
        """Run received command and return the output."""
        command = [CONF.virtualbox.vboxmanage_cmd, "--nologo"]
        command.extend(args)
        LOG.debug("Execute: %s", command)
        stdout, stderr = None, None
        for _ in range(CONF.virtualbox.retry_count):
            try:
                process = subprocess.Popen(
                    command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    universal_newlines=True)
            except subprocess.CalledProcessError as exc:
                stderr = exc.output
            else:
                stdout, stderr = process.communicate()

            if stderr and constants.VBOX_E_ACCESSDENIED in stderr:
                LOG.warning(_LW("Something went wrong, trying again."))
                time.sleep(CONF.virtualbox.retry_interval)
                continue

            break
        else:
            LOG.warning(_LW("Failed to process command."))

        return (stdout, stderr)

    @classmethod
    def _check_stderr(cls, stderr, instance=None, method=None):
        # TODO(alexandrucoman): Check for another common exceptions
        if constants.VBOX_E_INSTANCE_NOT_FOUND in stderr:
            raise exception.InstanceNotFound(instance=instance)

        if (constants.VBOX_E_INVALID_VM_STATE in stderr or
                constants.VBOX_E_INVALID_VM_STATE_2 in stderr):
            raise exception.InstanceInvalidState(
                instance=instance, method=method, details=stderr)

    @classmethod
    def list(cls, information):
        """Gives relevant information about host and information
        about VirtualBox's current settings.

        The following information are available with VBoxManage list:
            :HOST_INFO:         information about the host system
            :OSTYPES_INFO:      lists all guest operating systems
                                presently known to VirtualBox
            :VMS_INFO:          lists all virtual machines currently
                                registered with VirtualBox
            :RUNNINGVMS_INFO:   lists all currently running virtual
                                machines by their unique identifiers
        """
        output, error = cls._execute(cls.LIST, information)
        if error:
            raise exception.VBoxManageError(method=cls.LIST, reason=error)
        return output

    @classmethod
    def show_vm_info(cls, instance):
        """Show the configuration of a particular VM."""
        information = {}
        output, error = cls._execute(cls.SHOW_VM_INFO, instance,
                                     "--machinereadable")
        if error:
            cls._check_stderr(error, instance, cls.SHOW_VM_INFO)
            raise exception.VBoxManageError(method=cls.SHOW_VM_INFO,
                                            reason=error)

        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue

            key, separator, value = line.partition("=")
            value = value.strip(' "')
            key = key.strip(' "')
            if separator != "=":
                LOG.warning("Could not parse the following line: %s", line)
                continue

            information[key] = value if value != "none" else None

        return information

    @classmethod
    def modify_network(cls, instance, index, fields):
        """Change the network settings for a registered virtual machine.

        :param instance:
        :param index: specifies the virtual network adapter whose
                      settings should be changed.
        :param fileds: a list of field-value pairs

        The following fields are available with VBoxManage modify_network:
            :FIELD_NIC:             type of networking (nat, bridge etc)
            :FIELD_NIC_TYPE:        networking hardware
            :FIELD_CABLE_CONNECTED: connect / disconnect network
            :FIELD_BRIDGE_ADAPTER:  host interface used by virtual network
                                    interface
            :FILED_MAC_ADDRESS:     MAC address of the virtual network card
        """
        command = [cls.MODIFY_VM, instance]
        for field, value in fields:
            command.append(field % {"index": index})
            if value:
                command.append(value)

        _, error = cls._execute(*command)
        if error:
            raise exception.VBoxManageError(method="modifyvm", reason=error)

    @classmethod
    def update_network(cls, instance, index, field, value):
        """Update configuration of a virtual machine that is currently running.

        :param instance:
        :param index:       specifies the virtual network adapter whose
                            settings should be changed.
        :param field:       (str)
        :param value:       (list)

        The following fields are available with VBoxManage update_network:
            :FIELD_NIC:   type of networking (nat, bridge etc)
            :FIELD_LINK:  connects or disconnects virtual network cables
                          from their network interfaces.
        """
        _, error = cls._execute(cls.CONTROL_VM, instance, field %
                                {"index": index}, *value)

        if error:
            raise exception.VBoxManageError(method="controlvm", reason=error)


class VBoxNetworkManage(object):

    def __init__(self):
        self._nic = {}
        self._device_map = {}
        self._local_network = CONF.virtualbox.use_local_network
        self._vbox = VBoxManage()

    @property
    def local_network(self):
        """Test whether a NIC should be Host Only."""
        return self._local_network

    def _instances(self):
        """Return the names for all virtual machines currently
        registered with VirtualBox.
        """
        list_vms = self._vbox.list(constants.VMS_INFO)
        for virtual_machine in list_vms.splitlines():
            # Line format: "instance_name" {instance_uuid}
            try:
                name, _ = virtual_machine.split()
            except ValueError:
                continue
            yield name.strip('"')

    def _process_description(self, description):
        """Get information regarding network from the virtual machine
        description.
        """
        if not description:
            return False
        try:
            description = jsonutils.loads(description)["network"]
        except (ValueError, KeyError) as error:
            LOG.debug("Failed to load information from description: %(error)s",
                      {"error": error})
            return False

        for mac_address, device_id in description.items():
            self._device_map[mac_address] = device_id

        return True

    def _inspect_instance(self, instance_name):
        """Get the network information from an instance."""
        network = {}
        try:
            instace_info = self._vbox.show_vm_info(instance_name)
        except exception.InstanceNotFound:
            LOG.warning(_LW("Failed to get specification for `%(instance)s`"),
                        {"instance": instance_name})
            return

        description = instace_info.get(constants.VM_DESCRIPTION)
        if not self._process_description(description):
            LOG.warning(_LW("Invalid description for `%(instance)s`: "
                            "%(description)s"),
                        {"instance": instance_name,
                         "description": description})
            return

        for field, value in instace_info.items():
            if field[:-1] in constants.NETWORK_FIELDS:
                network.setdefault(field[-1], {})[field[:-1]] = value

        for nic_index in network:
            mac_address = network[nic_index].get(constants.MAC_ADDRESS)
            device_id = self._device_map.get(mac_address)
            nic_mode = network[nic_index].get(constants.NIC_MODE)

            if device_id and nic_mode != constants.NIC_MODE_NONE:
                self._nic[device_id] = network[nic_index]
                self._nic[device_id]["index"] = nic_index
                self._nic[device_id]["instance"] = instance_name
                self._nic[device_id]["state"] = instace_info.get(
                    constants.VM_STATE)

    def refresh(self):
        """Update internal database."""
        self._nic.clear()
        self._device_map.clear()
        for instance_name in self._instances():
            self._inspect_instance(instance_name)

    def device_exists(self, device_id):
        """Test whether a device exists."""
        return device_id in self._nic

    def devices(self):
        """Return a set with device id for all the devices."""
        return set(self._nic.keys())

    def _modify_network(self, device, physical_network):
        """Changes the network properties of a registered virtual machine.

        .. note:
            The virtual machine must be powered off.
        """

        if self.local_network:
            # Use host-only adaptor for this NIC
            adapter = constants.FIELD_HOSTONLY_ADAPTER
            nic_mode = constants.NIC_MODE_HOSTONLY
        else:
            # Use bridge adaptor for this NIC
            adapter = constants.FIELD_BRIDGE_ADAPTER
            nic_mode = constants.NIC_MODE_BRIDGED

        # Set networking hardware
        self._vbox.modify_network(
            device["instance"], device["index"],
            [
                (constants.FIELD_NIC_TYPE, CONF.virtualbox.nic_type),
                (constants.FIELD_NIC_MODE, nic_mode),
                (adapter, physical_network),
                (constants.FIELD_CABLE_CONNECTED, constants.ON)
            ])

    def _update_network(self, device, physical_network):
        """Change the network settings for a virtual machine.

        ..note:
             The virtual machine can be currently running.
        """
        if self.local_network:
            # Use Host Only NIC mode for this NIC
            nic_mode = constants.NIC_MODE_HOSTONLY
        else:
            # Use Bridge mode for this NIC
            nic_mode = constants.NIC_MODE_BRIDGED

        self._vbox.update_network(
            instance=device["instance"], index=device["index"],
            field=constants.FIELD_NIC,
            value=(nic_mode, physical_network))

        self._vbox.update_network(
            instance=device["instance"], index=device["index"],
            field=constants.FIELD_LINK_STATE,
            value=(constants.ON,))

    def setup_device(self, port_id, physical_network):
        """Connect the device to the specific interface."""
        device = self._nic.get(port_id)
        if not device:
            return

        if device["state"] == constants.POWER_OFF:
            try:
                self._modify_network(device, physical_network)
            except exception.VBoxManageError as error:
                # Probably the instance status was changed
                LOG.debug("Failed to modify network for %(device)s: "
                          "%(error)s",
                          {"device": device, "error": error})
            else:
                return

        self._update_network(device, physical_network)
