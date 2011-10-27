# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

from nova.api.openstack import extensions
from nova.api.openstack import servers
from nova.api.openstack import xmlutil
from nova import compute
from nova import log as logging

LOG = logging.getLogger('nova.api.openstack.contrib.disk_config')

ALIAS = 'RAX-DCF'
XMLNS_DCF = "http://docs.rackspacecloud.com/servers/api/ext/diskConfig/v1.0"


class ServerDiskConfigTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('server')
        root.set('{%s}diskConfig' % XMLNS_DCF, '%s:diskConfig' % ALIAS)
        return xmlutil.SlaveTemplate(root, 1, nsmap={ALIAS: XMLNS_DCF})


class ServersDiskConfigTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('servers')
        elem = xmlutil.SubTemplateElement(root, 'server', selector='servers')
        elem.set('{%s}diskConfig' % XMLNS_DCF, '%s:diskConfig' % ALIAS)
        return xmlutil.SlaveTemplate(root, 1, nsmap={ALIAS: XMLNS_DCF})


class Disk_config(extensions.ExtensionDescriptor):
    """Disk Management Extension"""

    name = "DiskConfig"
    alias = ALIAS
    namespace = XMLNS_DCF
    updated = "2011-09-27:00:00+00:00"

    def __init__(self, ext_mgr):
        super(Disk_config, self).__init__(ext_mgr)
        self.compute_api = compute.API()

    def _attach_server_slave_template(self, res, body):
        template = res.environ.get('nova.template')
        # NOTE(sirp): template is only used for XML serialization
        if template:
            if 'servers' in body:
                template.attach(ServersDiskConfigTemplate())
            else:
                template.attach(ServerDiskConfigTemplate())

    def _GET_servers(self, req, res, body):
        context = req.environ['nova.context']
        self._attach_server_slave_template(res, body)

        if 'servers' in body:
            servers = body['servers']
        else:
            servers = [body['server']]

        for server_dict in servers:
            # TODO(sirp): it would be nice to eliminate this extra lookup
            # FIXME(sirp): think johannes is fixing this fault stuff
            server = self.compute_api.routing_get(context, server_dict['id'])
            key = "%s:diskConfig" % ALIAS
            value = 'AUTO' if server['auto_disk_config'] else 'MANUAL'
            server_dict[key] = value

        return res

    def get_request_extensions(self):
        ReqExt = extensions.RequestExtension 
        return [
            ReqExt(method='GET',
                   url_route='/:(project_id)/servers/:(id)',
                   handler=self._GET_servers)
        ]
