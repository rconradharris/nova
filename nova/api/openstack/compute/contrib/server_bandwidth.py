#    Copyright 2012 Rackspace, US Inc.
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
#    under the License

"""Server Bandwidth Extension"""

from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import db
from nova import utils


ALIAS = "RAX-SERVER"
EXTENSION = "%s:bandwidth" % ALIAS
XMLNS_SB = "http://docs.rackspacecloud.com/servers/api/v1.0"


class ServerBandwidthTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement("server")
        return xmlutil.SlaveTemplate(root, 1, nsmap={ALIAS: XMLNS_SB})


class ServersBandwidthTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement("servers")
        elem = xmlutil.SubTemplateElement(root, "server", selector="servers")
        return xmlutil.SlaveTemplate(root, 1, nsmap={ALIAS: XMLNS_SB})


class ServerBandwidthController(wsgi.Controller):
    def _get_used_bw(self, context, servers):
        start_time = utils.current_audit_period()[0]
        uuids = [server["id"] for server in servers]
        db_instances = db.instance_get_all_by_filters(context,
                {'uuid': uuids})
        # Dictionary of 'mac address' -> 'bw usage'
        bw_usage_info = {}
        # Dictionary of 'instance uuid' -> list of 'bw_usage_info' entries
        instance_to_bw_usage = {}
        for db_instance in db_instances:
            nw_info = common.get_nw_info_for_instance(context, db_instance)
            for vif in nw_info:
                if not vif['network']:
                    continue
                mac = vif['address']
                if not mac:
                    continue
                instance_uuid = db_instance['uuid']
                bw_usage_info[mac] = {'interface': vif['network']['label']}
                if instance_uuid not in instance_to_bw_usage:
                    instance_to_bw_usage[instance_uuid] = []
                instance_to_bw_usage[instance_uuid].append(
                        bw_usage_info[mac])

        # NOTE(comstud): Grab bw usage for all mac addresses we care
        # about.  I suspect we can use iterkeys() instead of keys() to
        # make this slightly more efficient when dealing with lots of macs,
        # but I haven't tested it.  Playing it safe for now.
        bw_interfaces = db.bw_usage_get_by_macs(context,
                bw_usage_info.keys(), start_time)
        for bw_interface in bw_interfaces:
            mac = bw_interface['mac']
            bw_usage_info[mac].update(dict(
                    audit_period_start=bw_interface["start_period"],
                    audit_period_end=bw_interface["last_refreshed"],
                    bandwidth_inbound=bw_interface["bw_in"],
                    bandwidth_outbound=bw_interface["bw_out"]))

        for server in servers:
            bw_usages = instance_to_bw_usage.get(server['id'], [])
            # If db.bw_usage_get_by_macs didn't return entries for
            # certain macs, we end up with usage for a mac address
            # that only has a 'interface' key due to the setup when
            # iterating through db_instances above.  So, check that we
            # have a 'audit_period_start' key and only return those.
            server[EXTENSION] = [bw_usage
                    for bw_usage in bw_usages
                            if 'audit_period_start' in bw_usage]

    def _show(self, req, resp_obj):
        if "server" in resp_obj.obj:
            context = req.environ["nova.context"]
            resp_obj.attach(xml=ServerBandwidthTemplate())
            server = resp_obj.obj["server"]
            self._get_used_bw(context, [server])

    @wsgi.extends
    def show(self, req, resp_obj, id):
        self._show(req, resp_obj)

    @wsgi.extends
    def detail(self, req, resp_obj):
        if "servers" in resp_obj.obj:
            context = req.environ["nova.context"]
            resp_obj.attach(xml=ServersBandwidthTemplate())
            servers = resp_obj.obj["servers"]
            self._get_used_bw(context, servers)


class Server_bandwidth(extensions.ExtensionDescriptor):
    """Server Bandwidth Extension"""

    name = "ServerBandwidth"
    alias = ALIAS
    namespace = XMLNS_SB
    updated = "2012-01-19:00:00+00:00"

    def get_controller_extensions(self):
        servers_extension = extensions.ControllerExtension(self, "servers",
                ServerBandwidthController())

        return [servers_extension]
