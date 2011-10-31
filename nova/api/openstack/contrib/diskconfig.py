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

import json

from webob import exc
import webob

from nova import compute
from nova import exception
import nova.image
from nova import log as logging
from nova import network
from nova import rpc
from nova.api.openstack import faults
from nova.api.openstack import extensions
from nova.api.openstack import wsgi

LOG = logging.getLogger('nova.api.openstack.contrib.disk_config')


# FIXME(sirp): this is the old disk_config module, remove
class DiskConfigController(object):
    def __init__(self):
        self.compute_api = compute.API()

    def _return_dict(self, server_id, auto_disk_config):
        return {'server': {'id': server_id,
                           'auto_disk_config': auto_disk_config}}

    def index(self, req, server_id):
        context = req.environ['nova.context']
        try:
            server = self.compute_api.routing_get(context, server_id)
        except exception.NotFound:
            explanation = _("Server not found.")
            return faults.Fault(exc.HTTPNotFound(explanation=explanation))
        auto_disk_config = server['auto_disk_config'] or False
        return self._return_dict(server_id, auto_disk_config)

    def update(self, req, server_id, body=None):
        if not body:
            return faults.Fault(exc.HTTPUnprocessableEntity())
        context = req.environ['nova.context']
        try:
            server = self.compute_api.routing_get(context, server_id)
        except exception.NotFound:
            explanation = _("Server not found.")
            return faults.Fault(exc.HTTPNotFound(explanation=explanation))

        auto_disk_config = str(body['server'].get(
            'auto_disk_config', False)).lower()
        auto_disk_config = auto_disk_config == 'true' or False
        self.compute_api.update(context, server_id,
                auto_disk_config=auto_disk_config)

        return self._return_dict(server_id, auto_disk_config)


class ImageDiskConfigController(object):
    def __init__(self, image_service=None):
        self.compute_api = compute.API()
        self._image_service = image_service or \
                nova.image.get_default_image_service()

    def _return_dict(self, image_id, auto_disk_config):
        return {'image': {'id': image_id,
                'auto_disk_config': auto_disk_config}}

    def index(self, req, image_id):
        context = req.environ['nova.context']
        try:
            image = self._image_service.show(context, image_id)
        except (exception.NotFound, exception.InvalidImageRef):
            explanation = _("Image not found.")
            raise webob.exc.HTTPNotFound(explanation=explanation)
        image_properties = image.get('properties', None)
        if image_properties:
            auto_disk_config = image_properties.get('auto_disk_config', False)

        return self._return_dict(image_id, auto_disk_config)


class Diskconfig(extensions.ExtensionDescriptor):
    """Disk Configuration support"""

    name = "DiskConfig"
    alias = "OS-DCFG"
    namespace = "http://docs.openstack.org/ext/disk_config/api/v1.1"
    updated = "2011-08-31T00:00:00+00:00"

    def _server_extension_controller(self):
        metadata = {
            "attributes": {
                'auto_disk_config': ["server_id", "enabled"]}}

        body_serializers = {
            'application/xml': wsgi.XMLDictSerializer(metadata=metadata,
                                                      xmlns=wsgi.XMLNS_V11)}
        serializer = wsgi.ResponseSerializer(body_serializers, None)
        res = extensions.ResourceExtension(
            'os-disk-config',
            controller=DiskConfigController(),
            collection_actions={'update': 'PUT'},
            parent=dict(member_name='server', collection_name='servers'),
            serializer=serializer)
        return res

    def _image_extension_controller(self):
        resources = []
        metadata = {
            "attributes": {
                'auto_disk_config': ["image_id", "enabled"]}}

        body_serializers = {
            'application/xml': wsgi.XMLDictSerializer(metadata=metadata,
                                                      xmlns=wsgi.XMLNS_V11)}
        serializer = wsgi.ResponseSerializer(body_serializers, None)
        res = extensions.ResourceExtension(
            'os-disk-config',
            controller=ImageDiskConfigController(),
            collection_actions={'update': 'PUT'},
            parent=dict(member_name='image', collection_name='images'),
            serializer=serializer)
        return res

    def get_resources(self):
        return [self._server_extension_controller(),
                self._image_extension_controller()]
