# Copyright 2011 OpenStack LLC.
# All Rights Reserved.
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

"""The services extension."""

import os.path
import webob.exc

from nova.api.openstack.compute import servers
from nova.api.openstack.compute.views import servers as views_servers
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova.cells import api as cells_api
from nova import db
from nova import exception
from nova import flags
from nova.openstack.common import log as logging
from nova.openstack.common import rpc


FLAGS = flags.FLAGS
LOG = logging.getLogger("nova.api.contrib.services")


SERVICE_DB_ATTRS = ['id', 'host', 'topic', 'disabled', 'report_count',
                    'updated_at']

COMPUTE_NODE_ATTRS = ['vcpus', 'memory_mb', 'local_gb', 'vcpus_used',
                      'memory_mb_used', 'local_gb_used', 'hypervisor_type',
                      'hypervisor_version', 'cpu_info',
                      'hypervisor_hostname']


class ServicesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('services')
        elem = xmlutil.SubTemplateElement(root, 'service', selector='services')
        for attr in SERVICE_DB_ATTRS:
            elem.set(attr)
        elem.set('href')
        return xmlutil.MasterTemplate(root, 1, nsmap=nsmap)


def add_attr_elements(root, attrs):
    for attr in attrs:
        elem = xmlutil.SubTemplateElement(root, attr)
        elem.text = attr


class ServiceTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('service', selector='service')
        attrs = SERVICE_DB_ATTRS + ['href']
        add_attr_elements(root, attrs)
        return xmlutil.MasterTemplate(root, 1, nsmap=nsmap)


class VersionTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('version', selector='version')
        root.set('string')
        return xmlutil.MasterTemplate(root, 1, nsmap=nsmap)


class ConfigTemplateElement(xmlutil.TemplateElement):
    def will_render(self, datum):
        return True


class ConfigTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = ConfigTemplateElement('config', selector='config')
        elem = xmlutil.SubTemplateElement(root, 'item',
                                          selector=xmlutil.get_items)
        elem.set('key', 0)
        elem.text = 1
        return xmlutil.MasterTemplate(root, 1, nsmap=nsmap)


class DetailsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('details', selector='details')
        attrs = COMPUTE_NODE_ATTRS + ['memory_mb_used_servers']
        add_attr_elements(root, attrs)
        return xmlutil.MasterTemplate(root, 1, nsmap=nsmap)


def _build_service(base_url, service):
    service_info = {}
    for attr in SERVICE_DB_ATTRS:
        service_info[attr] = service[attr]

    href = os.path.join(base_url, 'services', str(service['id']))
    service_info['href'] = href
    return service_info


class ServicesController(object):
    """The Service API controller for the OpenStack API."""

    def __init__(self):
        self._view_builder = views_servers.ViewBuilder()

    @wsgi.serializers(xml=ServicesTemplate)
    def index(self, req):
        """Returns a list of services"""
        context = req.environ['nova.context']
        base_url = req.application_url
        services = db.service_get_all(context)
        return {"services": [_build_service(base_url, s) for s in services]}

    @staticmethod
    def _safe_service_get(context, id):
        try:
            return db.service_get(context, id)
        except exception.ServiceNotFound:
            raise webob.exc.HTTPNotFound()

    @wsgi.serializers(xml=ServiceTemplate)
    def show(self, req, id):
        context = req.environ['nova.context']
        service = self._safe_service_get(context, id)
        return {'service': _build_service(req.application_url, service)}

    @wsgi.serializers(xml=DetailsTemplate)
    def details(self, req, id):
        """Return service_type specific information for a service.

        For a 'compute' service, this will include used memory.
        """
        context = req.environ['nova.context']
        service = self._safe_service_get(context, id)

        details = {}

        topic = service['topic']
        if topic == 'compute':
            compute_node = db.compute_node_get_for_service(
                    context, service['id'])
            for attr in COMPUTE_NODE_ATTRS:
                details[attr] = compute_node[attr]

            instances = db.instance_get_all_by_host(context, service['host'])
            details['memory_mb_used_servers'] = sum(
                inst['memory_mb'] for inst in instances
                if inst['vm_state'] == 'active')

        return {'details': details}

    @classmethod
    def _call_method_for_service(cls, req, id, method):
        context = req.environ['nova.context']
        service = cls._safe_service_get(context, id)

        queue = rpc.queue_get_for(context, service['topic'], service['host'])
        data = rpc.call(context, queue, {'method': method})
        return data

    @wsgi.serializers(xml=VersionTemplate)
    def version(self, req, id):
        version = self._call_method_for_service(req, id, 'service_version')
        return {'version': {'string': version}}

    @wsgi.serializers(xml=ConfigTemplate)
    def config(self, req, id):
        config = self._call_method_for_service(req, id, 'service_config')
        return {'config': config}

    @wsgi.serializers(xml=servers.ServersTemplate)
    def servers(self, req, id):
        context = req.environ['nova.context']
        service = self._safe_service_get(context, id)
        instances = db.instance_get_all_by_host(context, service['host'])
        return self._view_builder.detail(req, instances)

    def disable(self, req, id):
        context = req.environ['nova.context']
        try:
            db.service_update(context, id, {'disabled': True})
        except exception.ServiceNotFound:
            raise webob.exc.HTTPNotFound()

    def enable(self, req, id):
        context = req.environ['nova.context']
        try:
            db.service_update(context, id, {'disabled': False})
        except exception.ServiceNotFound:
            raise webob.exc.HTTPNotFound()


class CellsServicesController(object):
    """The Service API controller for the OpenStack API. Works with cells."""

    def __init__(self):
        self._view_builder = views_servers.ViewBuilder()

    def _find_single_response(self, responses, match_cell_name=None):
        for (response, cell_name) in responses:
            if match_cell_name and cell_name == match_cell_name:
                return response
            elif match_cell_name is None and respose:
                return response

    def _get_all_services(self, context):
        """Get services locally, or from cells."""
        responses = cells_api.cell_broadcast_call(context,
                                                  "down",
                                                  "list_services")
        for (response, cell_name) in responses:
            for item in response:
                item["id"] = "%s-%s" % (cell_name, item["id"])
                yield item

    def _get_service_and_cell(self, context, service_id):
        """Get service locally, or from child cell."""
        responses = cells_api.cell_broadcast_call(context, "down",
                "get_service", service_id=service_id)
        for (response, cell_name) in responses:
            if response:
                return response, cell_name

    def _get_service(self, context, service_id):
        """Get service locally, or from child cell."""
        try:
            cell_name, service_id = service_id.split("-")
        except (ValueError, AttributeError):
            raise webob.exc.HTTPNotFound()
        responses = cells_api.cell_broadcast_call(context, "down",
                "get_service", service_id=service_id)
        return self._find_single_response(responses, match_cell_name=cell_name)

    def _get_compute_node(self, context, compute_id):
        """Get compute node information given a compute node id."""
        try:
            cell_name, compute_id = compute_id.split("-")
        except (ValueError, AttributeError):
            raise webob.exc.HTTPNotFound()
        responses = cells_api.cell_broadcast_call(context, "down",
                "compute_node_get", compute_node_id=compute_id)
        return self._find_single_response(responses, match_cell_name=cell_name)

    @wsgi.serializers(xml=ServicesTemplate)
    def index(self, req):
        """Returns a list of services"""
        context = req.environ['nova.context']
        base_url = req.application_url
        services = self._get_all_services(context)
        return {"services": [_build_service(base_url, s) for s in services]}

    @wsgi.serializers(xml=ServiceTemplate)
    def show(self, req, id):
        """Show summary of a specific service."""
        context = req.environ['nova.context']
        service = self._get_service(context, id)
        return {'service': _build_service(req.application_url, service)}

    @wsgi.serializers(xml=DetailsTemplate)
    def details(self, req, id):
        """Return service_type specific information for a service.

        For a 'compute' service, this will include used memory.
        """
        context = req.environ['nova.context']
        service = self._get_service(context, id)

        details = {}

        topic = service['topic']
        if topic == 'compute':
            compute_node = service["compute_node"][0]
            for attr in COMPUTE_NODE_ATTRS:
                details[attr] = compute_node[attr]

            instances = db.instance_get_all_by_host(context, service['host'])
            details['memory_mb_used_servers'] = sum(
                inst['memory_mb'] for inst in instances
                if inst['vm_state'] == 'active')

        return {'details': details}

    @wsgi.serializers(xml=servers.ServersTemplate)
    def servers(self, req, id):
        context = req.environ['nova.context']
        service = self._get_service(context, id)
        instances = db.instance_get_all_by_host(context, service['host'])
        return self._view_builder.detail(req, instances)

    @wsgi.serializers(xml=VersionTemplate)
    def version(self, req, id):
        raise webob.exc.HTTPNotImplemented()

    @wsgi.serializers(xml=ConfigTemplate)
    def config(self, req, id):
        raise webob.exc.HTTPNotImplemented()

    def disable(self, req, id):
        raise webob.exc.HTTPNotImplemented()

    def enable(self, req, id):
        raise webob.exc.HTTPNotImplemented()


if FLAGS.enable_cells:
    controller = CellsServicesController()
else:
    controller = ServicesController()


class Services(extensions.ExtensionDescriptor):
    """Services support"""

    name = "Services"
    alias = "services"
    namespace = "http://docs.openstack.org/ext/services/api/v1.1"
    updated = "2011-11-02T00:00:00+00:00"

    def get_resources(self):
        service = extensions.ResourceExtension('services',
                    controller,
                    member_actions={'config': 'GET',
                                    'details': 'GET',
                                    'servers': 'GET',
                                    'version': 'GET',
                                    'disable': 'POST',
                                    'enable': 'POST'})
        return [service]


nsmap = {None: xmlutil.XMLNS_V11, 'atom': xmlutil.XMLNS_ATOM}
