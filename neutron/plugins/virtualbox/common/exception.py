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

from neutron.common import exceptions
from neutron import i18n


class VBoxException(exceptions.NeutronException):
    message = i18n._('VBoxException: %(msg)s')


class VBoxManageError(VBoxException):
    message = i18n._("VBoxManage command %(method)s failed. "
                     "More information: %(reason)s")


class InstanceNotFound(VBoxException):
    message = i18n._("Instance %(instance)s could not be found.")


class InstanceInvalidState(VBoxManageError):
    message = i18n._("Instance %(instance)s cannot %(method)s while "
                     "the instance is in this state: %(details)s")
