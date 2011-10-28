
import nova.db.api
from nova import test

from nova.api import openstack
from nova.api.openstack import extensions
from nova.api.openstack import servers
from nova.api.openstack import wsgi
from nova.tests.api.openstack import fakes

from nova import utils

MANUAL_INSTANCE_UUID = fakes.FAKE_UUID
AUTO_INSTANCE_UUID = fakes.FAKE_UUID.replace('a', 'b')

stub_instance = fakes.stub_instance

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

        #fakes.stub_out_image_service(self.stubs)

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
