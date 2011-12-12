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

from nova import db
from nova import exception
from nova import log as logging
from nova import rpc
from nova.api.openstack import extensions
from nova.api.openstack import servers
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova.api.openstack.v2.views import servers as views_servers

from xml.dom import minidom


LOG = logging.getLogger("nova.api.contrib.services")


def _build_service(base_url, service):
    return {'id': service['id'],
            'href': os.path.join(base_url, 'services', str(service['id'])),
            'host': service['host'],
            'type': service['topic'],
            'enabled': not service['disabled'],
            'report_count': service['report_count'],
            'last_checkin': service['updated_at']}


def _build_compute_service(base_url, service, compute_node, instances):
    compute_info = _build_service(base_url, service)

    # db attributes
    exposed_attrs = ['vcpus', 'memory_mb', 'local_gb', 'vcpus_used',
                     'memory_mb_used', 'local_gb_used', 'hypervisor_type',
                     'hypervisor_version', 'cpu_info']
    for attr in exposed_attrs:
        compute_info[attr] = compute_node[attr]

    # computed attributes
    used_memory_mb_servers = sum(inst['memory_mb'] for inst in instances
                                 if inst['vm_state'] == 'active')
    compute_info['memory_mb_used_servers'] = used_memory_mb_servers
    return compute_info


class ServicesController(object):
    """The Service API controller for the OpenStack API."""

    def __init__(self):
        self._view_builder = views_servers.ViewBuilder()

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

    def show(self, req, id):
        context = req.environ['nova.context']
        service = self._safe_service_get(context, id)

        if service['topic'] == 'compute':
            compute_node = db.compute_node_get_for_service(
                    context, service['id'])
            instances = db.instance_get_all_by_host(context, service['host'])
            details = _build_compute_service(
                    req.application_url, service, compute_node, instances)
        else:
            details = _build_service(req.application_url, service)

        return {'service': details}

    @classmethod
    def _call_method_for_service(cls, req, id, method):
        context = req.environ['nova.context']
        service = cls._safe_service_get(context, id)

        queue = db.queue_get_for(context, service['topic'], service['host'])
        data = rpc.call(context, queue, {'method': method})
        return data

    def version(self, req, id):
        version = self._call_method_for_service(req, id, 'service_version')
        return {'version': {'string': version}}

    def config(self, req, id):
        config = self._call_method_for_service(req, id, 'service_config')
        return {'config': config}

    def servers(self, req, id):
        context = req.environ['nova.context']
        service = self._safe_service_get(context, id)

        if service['topic'] != 'compute':
            raise webob.ex.HTTPBadRequest(
                    'Can only request servers for compute service')

        compute_node = db.compute_node_get_for_service(
                context, service['id'])
        instances = db.instance_get_all_by_host(context, service['host'])
        return self._view_builder.detail(req, instances)


class Services(extensions.ExtensionDescriptor):
    """Services support"""

    name = "Services"
    alias = "services"
    namespace = "http://docs.openstack.org/ext/services/api/v1.1"
    updated = "2011-11-02T00:00:00+00:00"

    def get_resources(self):
        body_serializers = {'application/xml': ServiceXMLSerializer()}
        serializer = wsgi.ResponseSerializer(body_serializers, None)
        service = extensions.ResourceExtension('services',
                    ServicesController(),
                    serializer=serializer,
                    member_actions={'details': 'GET',
                                    'version': 'GET',
                                    'config': 'GET',
                                    'unitcount': 'GET',
                                    'servers': 'GET'})

        return [service]


nsmap = {None: xmlutil.XMLNS_V11, 'atom': xmlutil.XMLNS_ATOM}


class ServicesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('services')
        root.set('type')
        elem = xmlutil.SubTemplateElement(root, 'service', selector='services')
        elem.set('id')
        elem.set('href')
        elem.set('enabled')
        elem.set('report_count')
        elem.set('last_checkin')
        return xmlutil.MasterTemplate(root, 1, nsmap=nsmap)


class ServiceTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('service', selector='service')
        root.set('id')
        elem = xmlutil.SubTemplateElement(root, 'href')
        elem.text = 'href'
        elem = xmlutil.SubTemplateElement(root, 'enabled')
        elem.text = 'enabled'
        elem = xmlutil.SubTemplateElement(root, 'report_count')
        elem.text = 'report_count'
        elem = xmlutil.SubTemplateElement(root, 'last_checkin')
        elem.text = 'last_checkin'
        return xmlutil.MasterTemplate(root, 1, nsmap=nsmap)


class DetailsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('serviceDetails')
        elem = xmlutil.SubTemplateElement(root, 'item',
                                          selector='servicedetails')
        elem.set('name')
        elem.set('href')
        elem.set('description')
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


class UnitCountTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('unitCount', selector='unitcount')
        elem = xmlutil.SubTemplateElement(root, 'memory')
        elem.text = 'memory'
        elem = xmlutil.SubTemplateElement(root, 'disk')
        elem.text = 'disk'
        return xmlutil.MasterTemplate(root, 1, nsmap=nsmap)


class ServiceXMLSerializer(xmlutil.XMLTemplateSerializer):
    def index(self):
        return ServicesTemplate()

    def show(self):
        return ServiceTemplate()

    def details(self):
        return DetailsTemplate()

    def version(self):
        return VersionTemplate()

    def config(self):
        return ConfigTemplate()

    def unitcount(self):
        return UnitCountTemplate()

    def servers(self):
        return servers.ServersTemplate()
