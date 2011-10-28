
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

##def instance_update(context, instance_id, values):
##    return stub_instance(instance_id, name=values.get('display_name'))
##
##def fake_gen_uuid():
##    return FAKE_UUID


##def return_server_with_attributes(**kwargs):
##    def _return_server(context, id):
##        return stub_instance(id, **kwargs)
##    return _return_server
##
##
##def return_server_with_state(vm_state, task_state=None):
##    def _return_server(context, uuid):
##        return stub_instance(1, uuid=uuid, vm_state=vm_state,
##                             task_state=task_state)
##    return _return_server
##
##
##def return_server_with_uuid_and_state(vm_state, task_state):
##    def _return_server(context, id):
##        return stub_instance(id,
##                             uuid=FAKE_UUID,
##                             vm_state=vm_state,
##                             task_state=task_state)
##    return _return_server


##def return_servers(context, *args, **kwargs):
##    servers = []
##    for i in xrange(5):
##        server = stub_instance(i, 'fake', 'fake', uuid=get_fake_uuid(i))
##        servers.append(server)
##    return servers
##
##
##def return_servers_by_reservation(context, reservation_id=""):
##    return [stub_instance(i, reservation_id) for i in xrange(5)]
##
##
##def return_servers_by_reservation_empty(context, reservation_id=""):
##    return []
##
##
##def return_servers_from_child_zones_empty(*args, **kwargs):
##    return []


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

        #fakes.stub_out_networking(self.stubs)
        #fakes.stub_out_rate_limiting(self.stubs)
        #fakes.stub_out_key_pair_funcs(self.stubs)
        #fakes.stub_out_image_service(self.stubs)
        #self.stubs.Set(utils, 'gen_uuid', fake_gen_uuid)
        #self.stubs.Set(nova.db.api, 'instance_get_all_by_filters',
        #        return_servers)

        ##self.stubs.Set(nova.db.api, 'instance_get_by_uuid',
        ##               return_server_by_uuid)
        ##self.stubs.Set(nova.db.api, 'instance_get_all_by_project',
        ##               return_servers)
        #self.stubs.Set(nova.db.api, 'instance_add_security_group',
        #               return_security_group)
        ##self.stubs.Set(nova.db.api, 'instance_update', instance_update)
        ##self.stubs.Set(nova.db.api, 'instance_get_fixed_addresses',
        ##               instance_addresses)
        ##self.stubs.Set(nova.db.api, 'instance_get_floating_address',
        ##               instance_addresses)
        #self.stubs.Set(nova.compute.API, "get_diagnostics", fake_compute_api)
        #self.stubs.Set(nova.compute.API, "get_actions", fake_compute_api)
        #self.config_drive = None

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
