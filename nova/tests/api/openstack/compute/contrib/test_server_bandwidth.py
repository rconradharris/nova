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

import nova.db

from nova.api.openstack import compute
from nova import flags
from nova import test
from nova.tests.api.openstack import fakes
from nova import utils


EXTENSION = "RAX-SERVER:bandwidth"

INSTANCE_UUID_1 = fakes.FAKE_UUID
MACADDR1 = 'aa:aa:aa:aa:aa:aa'
INFO_CACHE_1 = [{'address': MACADDR1,
                 'id': 1,
                 'network': {'label': 'meow',
                             'subnets': []}}]
INSTANCE_UUID_2 = fakes.FAKE_UUID.replace("a", "b")
MACADDR2 = 'bb:bb:bb:bb:bb:bb'
INFO_CACHE_2 = [{'address': MACADDR2,
                 'id': 2,
                 'network': {'label': 'wuff',
                             'subnets': []}}]

FLAGS = flags.FLAGS


class ServerBandwidthTestCase(test.TestCase):
    def setUp(self):
        super(ServerBandwidthTestCase, self).setUp()

        self.fake_usages = {
                MACADDR1: {'mac': MACADDR1,
                           'start_period': 1234,
                           'last_refreshed': 5678,
                           'bw_in': 9012,
                           'bw_out': 3456},
                MACADDR2: {'mac': MACADDR2,
                           'start_period': 4321,
                           'last_refreshed': 8765,
                           'bw_in': 2109,
                           'bw_out': 6543}}

        FAKE_INSTANCES = [
            fakes.stub_instance(1, uuid=INSTANCE_UUID_1,
                    nw_cache=INFO_CACHE_1),
            fakes.stub_instance(2, uuid=INSTANCE_UUID_2,
                    nw_cache=INFO_CACHE_2)
        ]

        def fake_bw_usage_get_by_macs(context, macs, start_period):
            usage = []
            for mac in macs:
                usage.append(self.fake_usages[mac])
            return usage

        self.stubs.Set(nova.db, "bw_usage_get_by_macs",
                fake_bw_usage_get_by_macs)

        def fake_instance_get(context, id_):
            for instance in FAKE_INSTANCES:
                if id_ == instance["id"]:
                    return instance

        self.stubs.Set(nova.db, "instance_get", fake_instance_get)

        def fake_instance_get_by_uuid(context, uuid):
            for instance in FAKE_INSTANCES:
                if uuid == instance["uuid"]:
                    return instance

        self.stubs.Set(nova.db, "instance_get_by_uuid",
                fake_instance_get_by_uuid)

        def fake_instance_get_all(context, *args, **kwargs):
            return FAKE_INSTANCES

        self.stubs.Set(nova.db, "instance_get_all", fake_instance_get_all)
        self.stubs.Set(nova.db, "instance_get_all_by_filters",
                fake_instance_get_all)

        self.app = compute.APIRouter()

    def _bw_matches(self, ext, fake_usage):
        self.assertEqual(ext['audit_period_start'],
                fake_usage['start_period'])
        self.assertEqual(ext['audit_period_end'],
                fake_usage['last_refreshed'])
        self.assertEqual(ext['bandwidth_inbound'],
                fake_usage['bw_in'])
        self.assertEqual(ext['bandwidth_outbound'],
                fake_usage['bw_out'])

    def test_show_server(self):
        req = fakes.HTTPRequest.blank(
            "/fake/servers/%s" % INSTANCE_UUID_1)
        res = req.get_response(self.app)
        server_dict = utils.loads(res.body)["server"]
        self.assertTrue(EXTENSION in server_dict)
        self._bw_matches(server_dict[EXTENSION][0],
                self.fake_usages[MACADDR1])

    def test_detail_servers(self):
        req = fakes.HTTPRequest.blank("/fake/servers/detail")
        res = req.get_response(self.app)
        server_dicts = utils.loads(res.body)["servers"]

        for server_dict in server_dicts:
            self.assertTrue(EXTENSION in server_dict)
            ext = server_dict[EXTENSION][0]
            if ext['interface'] == 'meow':
                self._bw_matches(ext, self.fake_usages[MACADDR1])
            elif ext['interface'] == 'wuff':
                self._bw_matches(ext, self.fake_usages[MACADDR2])
            else:
                self.fail("interface name didn't match")
