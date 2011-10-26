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

import json
import webob

from nova import compute
from nova import exception
from nova import image
from nova import test
from nova.api.openstack.contrib.diskconfig import DiskConfigController
from nova.api.openstack.contrib.diskconfig import ImageDiskConfigController
from nova.tests.api.openstack import fakes


class DiskConfigTest(test.TestCase):

    def setUp(self):
        super(DiskConfigTest, self).setUp()
        self.uuid = '70f6db34-de8d-4fbd-aafb-4065bdfa6114'
        self.url = '/v1.1/openstack/servers/%s/os-disk-config' % self.uuid

    def test_retrieve_disk_config(self):
        def fake_compute_get(*args, **kwargs):
            return {'auto_disk_config': True}

        self.stubs.Set(compute.api.API, 'routing_get', fake_compute_get)
        req = webob.Request.blank(self.url)
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        body = json.loads(res.body)
        self.assertEqual(body['server']['auto_disk_config'], True)
        self.assertEqual(body['server']['id'], self.uuid)

    def test_set_disk_config(self):
        def fake_compute_get(*args, **kwargs):
            return {'auto_disk_config': 'True'}

        def fake_compute_update(*args, **kwargs):
            return {'auto_disk_config': 'False'}

        self.stubs.Set(compute.api.API, 'update', fake_compute_update)
        self.stubs.Set(compute.api.API, 'routing_get', fake_compute_get)

        req = webob.Request.blank(self.url)
        req.method = 'PUT'
        req.headers['Accept'] = 'application/json'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps({'server': {'auto_disk_config': False}})

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        body = json.loads(res.body)
        self.assertEqual(body['server']['auto_disk_config'], False)
        self.assertEqual(body['server']['id'], self.uuid)

    def test_retrieve_disk_config_bad_server_fails(self):
        def fake_compute_get(*args, **kwargs):
            raise exception.NotFound()

        self.stubs.Set(compute.api.API, 'routing_get', fake_compute_get)
        req = webob.Request.blank(self.url)
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 404)

    def test_set_disk_config_bad_server_fails(self):
        self.called = False

        def fake_compute_get(*args, **kwargs):
            raise exception.NotFound()

        def fake_compute_update(*args, **kwargs):
            self.called = True

        self.stubs.Set(compute.api.API, 'update', fake_compute_update)
        self.stubs.Set(compute.api.API, 'routing_get', fake_compute_get)

        req = webob.Request.blank(self.url)
        req.method = 'PUT'
        req.headers['Accept'] = 'application/json'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps({'server': {'auto_disk_config': False}})

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 404)
        self.assertEqual(self.called, False)


class ImageDiskConfigTest(test.TestCase):

    NOW_GLANCE_FORMAT = "2010-10-11T10:30:22"
    NOW_API_FORMAT = "2010-10-11T10:30:22Z"

    def test_image_get_disk_config(self):
        self.flags(image_service='nova.image.glance.GlanceImageService')
        fakes.stub_out_glance(self.stubs)

        def fake_image_service_show(*args, **kwargs):
            return {'properties': {'auto_disk_config': True}}

        self.stubs.Set(image.glance.GlanceImageService, 'show',
                       fake_image_service_show)

        req = webob.Request.blank('/v1.1/openstack/images/10/os-disk-config')
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)

        body = json.loads(res.body)

        self.assertEqual(body['image']['auto_disk_config'], True)
        self.assertEqual(int(body['image']['id']), 10)

    def test_image_get_disk_config_no_image_fails(self):
        self.flags(image_service='nova.image.glance.GlanceImageService')
        fakes.stub_out_glance(self.stubs)

        def fake_image_service_show(*args, **kwargs):
            raise exception.NotFound()

        self.stubs.Set(image.glance.GlanceImageService, 'show',
                       fake_image_service_show)

        req = webob.Request.blank('/v1.1/openstack/images/10/os-disk-config')
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 404)

    @classmethod
    def _make_image_fixtures(cls):
        image_id = 123
        base_attrs = {'created_at': cls.NOW_GLANCE_FORMAT,
                      'updated_at': cls.NOW_GLANCE_FORMAT,
                      'deleted_at': None,
                      'deleted': False}

        fixtures = []

        def add_fixture(**kwargs):
            kwargs.update(base_attrs)
            fixtures.append(kwargs)

        # Public image
        add_fixture(id=1, name='snapshot', is_public=False,
                    status='active', properties={})

        return fixtures
