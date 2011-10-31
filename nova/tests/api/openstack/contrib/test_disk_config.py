# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
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
import datetime

import nova.db.api
import nova.rpc

from nova import flags
from nova import test
from nova import utils
from nova.api import openstack
from nova.api.openstack import extensions
from nova.api.openstack import servers
from nova.api.openstack import wsgi
from nova.tests.api.openstack import fakes

MANUAL_INSTANCE_UUID = fakes.FAKE_UUID
AUTO_INSTANCE_UUID = fakes.FAKE_UUID.replace('a', 'b')

stub_instance = fakes.stub_instance
FLAGS = flags.FLAGS


def instance_addresses(context, instance_id):
    return None


class DiskConfigTestCase(test.TestCase):

    def setUp(self):
        super(DiskConfigTestCase, self).setUp()
        self.flags(verbose=True)
        fakes.stub_out_nw_api(self.stubs)

        FAKE_INSTANCES = [
            fakes.stub_instance(1,
                                uuid=MANUAL_INSTANCE_UUID,
                                auto_disk_config=False),
            fakes.stub_instance(2,
                                uuid=AUTO_INSTANCE_UUID,
                                auto_disk_config=True)
        ]

        def fake_instance_get(context, id_):
            for instance in FAKE_INSTANCES:
                if id_ == instance['id']:
                    return instance

        self.stubs.Set(nova.db.api, 'instance_get', fake_instance_get)

        def fake_instance_get_by_uuid(context, uuid):
            for instance in FAKE_INSTANCES:
                if uuid == instance['uuid']:
                    return instance

        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                       fake_instance_get_by_uuid)

        def fake_instance_get_all(context, *args, **kwargs):
            return FAKE_INSTANCES

        self.stubs.Set(nova.db, 'instance_get_all', fake_instance_get_all)
        self.stubs.Set(nova.db.api, 'instance_get_all_by_filters',
                       fake_instance_get_all)

        def instance_create(context, inst):
            inst['id'] = 1
            inst['uuid'] = AUTO_INSTANCE_UUID
            inst['created_at'] = datetime.datetime(2010, 10, 10, 12, 0, 0)
            inst['updated_at'] = datetime.datetime(2010, 10, 10, 12, 0, 0)
            inst['progress'] = 0

            def fake_instance_get_for_create(context, id_):
                return inst

            self.stubs.Set(nova.db.api, 'instance_get',
                          fake_instance_get_for_create)
            return inst

        def rpc_call_wrapper(context, topic, msg):
            """Stub out the scheduler creating the instance entry"""
            if topic == FLAGS.scheduler_topic and \
                    msg['method'] == 'run_instance':
                request_spec = msg['args']['request_spec']
                num_instances = request_spec.get('num_instances', 1)
                instances = []
                for x in xrange(num_instances):
                    instances.append(instance_create(context,
                        request_spec['instance_properties']))
                return instances

        self.stubs.Set(nova.rpc, 'call', rpc_call_wrapper)

        app = openstack.APIRouter()
        app = extensions.ExtensionMiddleware(app)
        app = wsgi.LazySerializationMiddleware(app)
        self.app = app

    def assertDiskConfig(self, dict_, value):
        self.assert_('RAX-DCF:diskConfig' in dict_)
        self.assertEqual(dict_['RAX-DCF:diskConfig'], value)

    def test_show_server(self):
        req = fakes.HTTPRequest.blank(
            '/fake/servers/%s' % MANUAL_INSTANCE_UUID)
        res = req.get_response(self.app)
        server_dict = utils.loads(res.body)['server']
        self.assertDiskConfig(server_dict, 'MANUAL')

        req = fakes.HTTPRequest.blank(
            '/fake/servers/%s' % AUTO_INSTANCE_UUID)
        res = req.get_response(self.app)
        server_dict = utils.loads(res.body)['server']
        self.assertDiskConfig(server_dict, 'AUTO')

    def test_detail_servers(self):
        req = fakes.HTTPRequest.blank('/fake/servers/detail')
        res = req.get_response(self.app)
        server_dicts = utils.loads(res.body)['servers']

        expectations = ['MANUAL', 'AUTO']
        for server_dict, expected in zip(server_dicts, expectations):
            self.assertDiskConfig(server_dict, expected)

    def test_show_image(self):
        req = fakes.HTTPRequest.blank('/fake/images/6')
        res = req.get_response(self.app)
        image_dict = utils.loads(res.body)['image']
        self.assertDiskConfig(image_dict, 'MANUAL')

        req = fakes.HTTPRequest.blank('/fake/images/7')
        res = req.get_response(self.app)
        image_dict = utils.loads(res.body)['image']
        self.assertDiskConfig(image_dict, 'AUTO')

    def test_detail_image(self):
        req = fakes.HTTPRequest.blank('/fake/images/detail')
        res = req.get_response(self.app)
        image_dicts = utils.loads(res.body)['images']

        expectations = ['MANUAL', 'AUTO']
        for image_dict, expected in zip(image_dicts, expectations):
            # NOTE(sirp): image fixtures 6 and 7 are setup for
            # auto_disk_config testing
            if image_dict['id'] in (6, 7):
                self.assertDiskConfig(image_dict, expected)

    def test_create_server_override_auto(self):
        req = fakes.HTTPRequest.blank('/fake/servers')
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {'server': {
                  'name': 'server_test',
                  'imageRef': '1',
                  'flavorRef': '1',
                  'RAX-DCF:diskConfig': 'AUTO'
               }}

        req.body = utils.dumps(body)
        res = req.get_response(self.app)
        server_dict = utils.loads(res.body)['server']
        self.assertDiskConfig(server_dict, 'AUTO')

    def test_create_server_override_manual(self):
        req = fakes.HTTPRequest.blank('/fake/servers')
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {'server': {
                  'name': 'server_test',
                  'imageRef': '1',
                  'flavorRef': '1',
                  'RAX-DCF:diskConfig': 'MANUAL'
               }}

        req.body = utils.dumps(body)
        res = req.get_response(self.app)
        server_dict = utils.loads(res.body)['server']
        self.assertDiskConfig(server_dict, 'MANUAL')

    def test_create_server_detect_from_image(self):
        """If user doesn't pass in diskConfig for server, use image metadata
        to specify AUTO or MANUAL.
        """
        req = fakes.HTTPRequest.blank('/fake/servers')
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {'server': {
                  'name': 'server_test',
                  'imageRef': '6',
                  'flavorRef': '1',
               }}

        req.body = utils.dumps(body)
        res = req.get_response(self.app)
        server_dict = utils.loads(res.body)['server']
        self.assertDiskConfig(server_dict, 'MANUAL')

        req = fakes.HTTPRequest.blank('/fake/servers')
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {'server': {
                  'name': 'server_test',
                  'imageRef': '7',
                  'flavorRef': '1',
               }}

        req.body = utils.dumps(body)
        res = req.get_response(self.app)
        server_dict = utils.loads(res.body)['server']
        self.assertDiskConfig(server_dict, 'AUTO')
