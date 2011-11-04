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
from xml.dom import minidom

from nova.api.openstack import extensions
from nova.api.openstack import servers
from nova.api.openstack import xmlutil
from nova import compute
from nova import log as logging
from nova import utils

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


class ImageDiskConfigTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('image')
        root.set('{%s}diskConfig' % XMLNS_DCF, '%s:diskConfig' % ALIAS)
        return xmlutil.SlaveTemplate(root, 1, nsmap={ALIAS: XMLNS_DCF})


class ImagesDiskConfigTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('images')
        elem = xmlutil.SubTemplateElement(root, 'image', selector='images')
        elem.set('{%s}diskConfig' % XMLNS_DCF, '%s:diskConfig' % ALIAS)
        return xmlutil.SlaveTemplate(root, 1, nsmap={ALIAS: XMLNS_DCF})


class Disk_config(extensions.ExtensionDescriptor):
    """Disk Management Extension"""

    name = "DiskConfig"
    alias = ALIAS
    namespace = XMLNS_DCF
    updated = "2011-09-27:00:00+00:00"

    API_DISK_CONFIG = "%s:diskConfig" % ALIAS
    INTERNAL_DISK_CONFIG = "auto_disk_config"

    def __init__(self, ext_mgr):
        super(Disk_config, self).__init__(ext_mgr)
        self.compute_api = compute.API()

    def _GET_servers(self, req, res, body):
        context = req.environ['nova.context']

        # If using XML, use serialization template
        template = res.environ.get('nova.template')
        if template:
            if 'servers' in body:
                template.attach(ServersDiskConfigTemplate())
            else:
                template.attach(ServerDiskConfigTemplate())

        if 'servers' in body:
            servers = body['servers']
        elif 'server' in body:
            servers = [body['server']]
        else:
            servers = []

        for server in servers:
            # TODO(sirp): it would be nice to eliminate this extra lookup
            db_server = self.compute_api.routing_get(context, server['id'])

            value = db_server[self.INTERNAL_DISK_CONFIG]
            api_value = 'AUTO' if value else 'MANUAL'

            server[self.API_DISK_CONFIG] = api_value

        return res

    def _GET_images(self, req, res, body):
        template = res.environ.get('nova.template')
        if template:
            if 'images' in body:
                template.attach(ImagesDiskConfigTemplate())
            else:
                template.attach(ImageDiskConfigTemplate())

        images = body['images'] if 'images' in body else [body['image']]
        for image in images:
            metadata = image['metadata']
            if self.INTERNAL_DISK_CONFIG in metadata:

                raw_value = metadata[self.INTERNAL_DISK_CONFIG]
                value = utils.bool_from_str(raw_value)
                api_value = 'AUTO' if value else 'MANUAL'

                image[self.API_DISK_CONFIG] = api_value

        return res

    def _POST_servers(self, req, res, body):
        return self._GET_servers(req, res, body)

    def _pre_POST_servers(self, req):
        # NOTE(sirp): in an ideal world, extensions shouldn't have to worry
        # about serialization--that would be handled exclusively by
        # middleware. Unfortunately, until we refactor extensions to better
        # support pre-processing extensions (puttinng in place an
        # EagerDeserialization middleware similar to our LazySerialization),
        # we'll need to keep this hack in place.

        content_type = req.content_type
        if 'xml' in content_type:
            node = minidom.parseString(req.body)
            server = node.getElementsByTagName('server')[0]
            api_value = server.getAttribute(self.API_DISK_CONFIG)
            if api_value:
                value = api_value == 'AUTO'
                server.setAttribute(self.INTERNAL_DISK_CONFIG, str(value))
                req.body = str(node.toxml())
        else:
            body = utils.loads(req.body)
            server = body['server']
            api_value = server.get(self.API_DISK_CONFIG)
            if api_value:
                value = api_value == 'AUTO'
                server[self.INTERNAL_DISK_CONFIG] = value
                req.body = utils.dumps(body)

    def get_request_extensions(self):
        ReqExt = extensions.RequestExtension
        return [
            ReqExt(method='GET',
                   url_route='/:(project_id)/servers/:(id)',
                   handler=self._GET_servers),
            ReqExt(method='POST',
                   url_route='/:(project_id)/servers',
                   handler=self._POST_servers,
                   pre_handler=self._pre_POST_servers),
            ReqExt(method='GET',
                   url_route='/:(project_id)/images/:(id)',
                   handler=self._GET_images)
        ]
