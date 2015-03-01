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

FIELD_LINK_STATE = "setlinkstate%(index)s"
FIELD_NIC = "nic%(index)s"
FIELD_NIC_MODE = "--nic%(index)s"
FIELD_NIC_TYPE = "--nictype%(index)s"
FIELD_CABLE_CONNECTED = "--cableconnected%(index)s"
FIELD_BRIDGE_ADAPTER = "--bridgeadapter%(index)s"
FIELD_HOSTONLY_ADAPTER = '--hostonlyadapter%(index)s'
FILED_MAC_ADDRESS = "--macaddress%(index)s"

BRIDGE_ADAPTER = 'bridgeadapter'
HOSTONLY_ADAPTER = 'hostonlyadapter'
IS_CONNECTED = 'cableconnected'
MAC_ADDRESS = 'macaddress'
NIC_MODE = 'nic'
NIC_TYPE = 'nictype'
NIC_SPEED = 'nicspeed'
NETWORK_FIELDS = (IS_CONNECTED, MAC_ADDRESS, NIC_MODE, NIC_TYPE, NIC_SPEED,
                  BRIDGE_ADAPTER, HOSTONLY_ADAPTER)

NIC_MODE_NONE = 'none'
NIC_MODE_NULL = 'null'
NIC_MODE_NAT = 'nat'
NIC_MODE_BRIDGED = 'bridged'
NIC_MODE_INTNET = 'intnet'
NIC_MODE_HOSTONLY = 'hostonly'
NIC_MODE_GENERIC = 'generic'

NIC_TYPE_AM79C970A = 'Am79C970A'    # AMD PCNet PCI II
NIC_TYPE_AM79C973 = 'Am79C973'      # AMD PCNet FAST III
NIC_TYPE_82540EM = '82540EM'        # Intel PRO/1000 MT Desktop
NIC_TYPE_82543GC = '82543GC'        # Intel PRO/1000 T Server
NIC_TYPE_82545EM = '82545EM'        # Intel PRO/1000 MT Server
NIC_TYPE_VIRTIO = 'virtio'          # Paravirtualized network adapter

ON = 'on'
OFF = 'off'

VM_STATE = 'VMState'
VM_DESCRIPTION = 'description'
POWER_OFF = 'poweroff'
RUNNING = 'running'

VBOX_E_ACCESSDENIED = 'E_ACCESSDENIED'
VBOX_E_INVALID_OBJECT_STATE = 'VBOX_E_INVALID_OBJECT_STATE'
VBOX_E_INVALID_VM_STATE = 'VBOX_E_INVALID_VM_STATE'
VBOX_E_INVALID_VM_STATE_2 = 'Machine in invalid state'
VBOX_E_OBJECT_NOT_FOUND = 'VBOX_E_OBJECT_NOT_FOUND'
VBOX_E_INSTANCE_NOT_FOUND = 'Could not find a registered machine named'

# RPC API default version
RPC_VERSION = '1.1'

# Topic for tunnel notifications between the plugin and agent
TUNNEL = 'tunnel'

VMS_INFO = 'vms'
