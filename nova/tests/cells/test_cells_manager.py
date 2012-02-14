# Copyright (c) 2012 Openstack, LLC
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
"""
Tests For CellsManager
"""

from nova.cells import common as cells_common
from nova.cells import manager as cells_manager
from nova import db
from nova import exception
from nova import flags
from nova.rpc import common as rpc_common
from nova import test
from nova.tests.cells import fakes


FLAGS = flags.FLAGS


class CellsManagerTestCase(test.TestCase):
    """Test case for CellsManager class"""

    def setUp(self):
        super(CellsManagerTestCase, self).setUp()
        self.flags(cell_name='me')
        fakes.init()

        self.cells_manager = fakes.FakeCellsManager(
                _test_case=self,
                _my_name=FLAGS.cell_name,
                cells_driver_cls=fakes.FakeCellsDriver,
                cells_scheduler_cls=fakes.FakeCellsScheduler)

    def test_setup(self):
        self.assertEqual(self.cells_manager.my_cell_info.name,
                FLAGS.cell_name)
        self.assertTrue(self.cells_manager.my_cell_info.is_me)

    def test_refresh_cells(self):
        fake_context = 'fake_context'

        def verify_cells(cells):
            total_cells_found = (len(self.cells_manager.child_cells) +
                    len(self.cells_manager.parent_cells))
            for cell in cells:
                if cell['is_parent']:
                    self.assertIn(cell['name'],
                            self.cells_manager.parent_cells)
                else:
                    self.assertIn(cell['name'],
                            self.cells_manager.child_cells)
            self.assertEqual(len(cells), total_cells_found)

        verify_cells(fakes.FAKE_CELLS[FLAGS.cell_name])

        # Different list of cells
        fakes.stubout_cell_get_all_for_refresh(self.cells_manager)
        self.cells_manager._refresh_cells_from_db(fake_context)
        verify_cells(fakes.FAKE_CELLS_REFRESH)

    def _find_next_hop(self, dest_cell_name, routing_path, direction):
        return self.cells_manager._find_next_hop(dest_cell_name,
                routing_path, direction)

    def test_find_next_hop_is_me(self):
        cell_info = self._find_next_hop('a.b.c', 'a.b.c', 'up')
        self.assertTrue(cell_info.is_me)
        cell_info = self._find_next_hop('a.b.c', 'a.b.c', 'down')
        self.assertTrue(cell_info.is_me)
        cell_info = self._find_next_hop('a', 'a', 'up')
        self.assertTrue(cell_info.is_me)
        cell_info = self._find_next_hop('a', 'a', 'down')
        self.assertTrue(cell_info.is_me)

    def test_find_next_hop_inconsistency(self):
        self.assertRaises(exception.CellRoutingInconsistency,
                self._find_next_hop, 'a.b.d', 'a.b.c', 'up')
        self.assertRaises(exception.CellRoutingInconsistency,
                self._find_next_hop, 'a.b.d', 'a.b.c', 'down')
        # Too many hops in routing path
        self.assertRaises(exception.CellRoutingInconsistency,
                self._find_next_hop, 'a.b', 'a.b.c', 'down')
        self.assertRaises(exception.CellRoutingInconsistency,
                self._find_next_hop, 'a.b', 'a.b.c', 'up')

    def test_find_next_hop_child_not_found(self):
        dest_cell = 'me.notfound'
        routing_path = 'me'
        self.assertRaises(exception.CellRoutingInconsistency,
                self._find_next_hop, dest_cell, routing_path, 'down')

    def test_find_next_hop_parent_not_found(self):
        dest_cell = 'me.notfound'
        routing_path = 'me'
        self.assertRaises(exception.CellRoutingInconsistency,
                self._find_next_hop, dest_cell, routing_path, 'up')

    def test_find_next_hop_direct_child_cell(self):
        # Find a child cell that we stubbed
        child_cell = fakes.find_a_child_cell(FLAGS.cell_name)

        dest_cell = FLAGS.cell_name + '.' + child_cell['name']
        routing_path = 'me'

        cell_info = self._find_next_hop(dest_cell, routing_path, 'down')
        self.assertEqual(cell_info.name, child_cell['name'])

    def test_find_next_hop_grandchild_cell(self):
        # Find a child cell that we stubbed
        child_cell = fakes.find_a_child_cell(FLAGS.cell_name)

        dest_cell = FLAGS.cell_name + '.' + child_cell['name'] + '.grandchild'
        routing_path = 'me'

        cell_info = self._find_next_hop(dest_cell, routing_path, 'down')
        self.assertEqual(cell_info.name, child_cell['name'])

    def test_find_next_hop_direct_parent_cell(self):
        # Find a parent cell that we stubbed
        parent_cell = fakes.find_a_parent_cell(FLAGS.cell_name)

        # When going up, the path is reversed
        dest_cell = FLAGS.cell_name + '.' + parent_cell['name']
        routing_path = 'me'
        cell_info = self._find_next_hop(dest_cell, routing_path, 'up')
        self.assertEqual(cell_info.name, parent_cell['name'])

        # Multi-level
        dest_cell = 'a.b.me.' + parent_cell['name']
        routing_path = 'a.b.me'
        cell_info = self._find_next_hop(dest_cell, routing_path, 'up')
        self.assertEqual(cell_info.name, parent_cell['name'])

    def test_find_next_hop_grandparent_cell(self):
        # Find a parent cell that we stubbed
        parent_cell = fakes.find_a_parent_cell(FLAGS.cell_name)

        # When going up, the path is reversed
        dest_cell = (FLAGS.cell_name + '.' + parent_cell['name'] +
                '.grandparent')
        routing_path = 'me'
        cell_info = self._find_next_hop(dest_cell, routing_path, 'up')
        self.assertEqual(cell_info.name, parent_cell['name'])

        # Multi-level
        dest_cell = 'a.b.me.' + parent_cell['name'] + '.grandparent'
        routing_path = 'a.b.me'
        cell_info = self._find_next_hop(dest_cell, routing_path, 'up')
        self.assertEqual(cell_info.name, parent_cell['name'])

    def test_route_message_to_self_happy_day(self):
        """Test happy day call to my cell returning a response."""

        fake_context = 'fake_context'
        message = {'method': 'test_method',
                   'args': fakes.TEST_METHOD_EXPECTED_KWARGS}
        args = {'dest_cell_name': FLAGS.cell_name,
                'routing_path': None,
                'direction': 'down',
                'message': message,
                'need_response': True}

        result = self.cells_manager.route_message(fake_context, **args)
        self.assertEqual(result, fakes.TEST_METHOD_EXPECTED_RESULT)

    def test_route_message_to_grandchild_happy_day(self):
        """Test happy day call to grandchild cell returning a response."""
        fake_context = 'fake_context'

        message = {'method': 'test_method',
                   'args': fakes.TEST_METHOD_EXPECTED_KWARGS}
        args = {'dest_cell_name': 'me.cell2.grandchild',
                'routing_path': None,
                'direction': 'down',
                'message': message,
                'need_response': True}
        result = self.cells_manager.route_message(fake_context, **args)
        self.assertEqual(result, fakes.TEST_METHOD_EXPECTED_RESULT)

    def test_route_message_to_grandchild_with_exception(self):
        """Test call to grandchild cell raising an exception."""
        fake_context = 'fake_context'

        gc_mgr = fakes.FAKE_CELL_MANAGERS['grandchild']

        def fake_test_method(context, **kwargs):
            raise Exception('exception in grandchild')

        self.stubs.Set(gc_mgr, 'test_method', fake_test_method)

        message = {'method': 'test_method',
                   'args': fakes.TEST_METHOD_EXPECTED_KWARGS}
        args = {'dest_cell_name': 'me.cell2.grandchild',
                'routing_path': None,
                'direction': 'down',
                'message': message,
                'need_response': True}

        try:
            self.cells_manager.route_message(fake_context, **args)
        except rpc_common.RemoteError, e:
            self.assertIn('exception in grandchild', str(e))
        else:
            self.fail("rpc.common.RemoteError not raised")

    def test_broadcast_message_down(self):
        """Test broadcast to all child/grandchild cells."""
        fake_context = 'fake_context'

        bcast_message = cells_common.form_broadcast_message('down',
                'test_method', fakes.TEST_METHOD_EXPECTED_KWARGS)
        self.assertEqual(bcast_message['method'], 'broadcast_message')

        self.cells_manager.broadcast_message(fake_context,
                **bcast_message['args'])

        self.assertEqual(self.cells_manager._test_call_info['send_message'],
                len(self.cells_manager.get_child_cells()))
        self.assertEqual(self.cells_manager._test_call_info['test_method'], 1)
        z2_mgr = fakes.FAKE_CELL_MANAGERS['cell2']
        self.assertEqual(z2_mgr._test_call_info['send_message'],
                len(z2_mgr.get_child_cells()))
        self.assertEqual(z2_mgr._test_call_info['test_method'], 1)
        gc_mgr = fakes.FAKE_CELL_MANAGERS['grandchild']
        self.assertEqual(gc_mgr._test_call_info['send_message'], 0)
        self.assertEqual(gc_mgr._test_call_info['test_method'], 1)

    def test_broadcast_message_up(self):
        """Test broadcast from grandchild cells up."""
        fake_context = 'fake_context'

        gc_mgr = fakes.FAKE_CELL_MANAGERS['grandchild']
        bcast_message = cells_common.form_broadcast_message('up',
                'test_method', fakes.TEST_METHOD_EXPECTED_KWARGS)
        self.assertEqual(bcast_message['method'], 'broadcast_message')

        gc_mgr.broadcast_message(fake_context, **bcast_message['args'])

        self.assertEqual(gc_mgr._test_call_info['send_message'],
                len(gc_mgr.get_parent_cells()))
        self.assertEqual(gc_mgr._test_call_info['test_method'], 1)
        z2_mgr = fakes.FAKE_CELL_MANAGERS['cell2']
        self.assertEqual(z2_mgr._test_call_info['send_message'],
                len(z2_mgr.get_parent_cells()))
        self.assertEqual(z2_mgr._test_call_info['test_method'], 1)
        self.assertEqual(self.cells_manager._test_call_info['send_message'],
                len(self.cells_manager.get_parent_cells()))
        self.assertEqual(self.cells_manager._test_call_info['test_method'], 1)

    def test_broadcast_message_max_hops(self):
        """Test broadcast stops when reaching max hops."""
        self.flags(cell_max_broadcast_hop_count=1)
        fake_context = 'fake_context'

        bcast_message = cells_common.form_broadcast_message('down',
                'test_method', fakes.TEST_METHOD_EXPECTED_KWARGS)
        self.assertEqual(bcast_message['method'], 'broadcast_message')

        self.cells_manager.broadcast_message(fake_context,
                **bcast_message['args'])

        self.assertEqual(self.cells_manager._test_call_info['send_message'],
                len(self.cells_manager.get_child_cells()))
        self.assertEqual(self.cells_manager._test_call_info['test_method'], 1)
        z2_mgr = fakes.FAKE_CELL_MANAGERS['cell2']
        self.assertEqual(z2_mgr._test_call_info['send_message'],
                len(z2_mgr.get_child_cells()))
        self.assertEqual(z2_mgr._test_call_info['test_method'], 1)
        gc_mgr = fakes.FAKE_CELL_MANAGERS['grandchild']
        self.assertEqual(gc_mgr._test_call_info['send_message'], 0)
        self.assertEqual(gc_mgr._test_call_info['test_method'], 0)

    def test_run_service_api_method(self):

        compute_api = self.cells_manager.api_map['compute']

        call_info = {'compute': 0}

        fake_instance = 'fake_instance'
        fake_context = 'fake_context'

        def fake_instance_get(*args, **kwargs):
            return fake_instance

        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get)

        def compute_method(context, instance, arg1, arg2,
                kwarg1=None, kwarg2=None):
            self.assertEqual(instance, fake_instance)
            self.assertEqual(context, fake_context)
            self.assertEqual(arg1, 1)
            self.assertEqual(arg2, 2)
            self.assertEqual(kwarg1, 3)
            self.assertEqual(kwarg2, 4)
            call_info['compute'] += 1

        compute_api.compute_method = compute_method

        method_info = {'method': 'compute_method',
                       'method_args': ('uuid', 1, 2),
                       'method_kwargs': {'kwarg1': 3, 'kwarg2': 4}}
        self.cells_manager.run_service_api_method(fake_context,
                'compute', method_info)

    def test_run_service_api_method_unknown_service(self):
        self.assertRaises(exception.CellServiceAPIMethodNotFound,
                self.cells_manager.run_service_api_method, 'fake_context',
                'unknown', None)

    def test_run_service_api_method_unknown(self):
        method_info = {'method': 'unknown'}
        self.assertRaises(exception.CellServiceAPIMethodNotFound,
                self.cells_manager.run_service_api_method, 'fake_context',
                'compute', method_info)

    def test_instance_update(self):
        fake_context = 'fake_context'

        instance_info = {'uuid': 'fake_uuid', 'updated_at': 'foo'}
        call_info = {'instance_update': 0}

        def fake_instance_update(context, uuid, values):
            expected_values = instance_info.copy()
            # Need to make sure the correct cell ended up in here based
            # on the routing path.  Since updates flow up, the cell
            # name is the reverse of the routing path
            expected_values['cell_name'] = 'a.b.c.d.e'
            self.assertEqual(uuid, instance_info['uuid'])
            self.assertEqual(values, expected_values)
            call_info['instance_update'] += 1

        self.stubs.Set(db, 'instance_update', fake_instance_update)

        # We have a parent listed in the default cell_get_all, so reset
        # this so we'll update
        self.cells_manager.parent_cells = {}
        self.cells_manager.instance_update(fake_context, instance_info,
                routing_path='e.d.c.b.a')
        self.assertEqual(call_info['instance_update'], 1)

    def test_instance_update_ignored_when_not_at_top(self):
        fake_context = 'fake_context'

        instance_info = {'uuid': 'fake_uuid', 'updated_at': 'foo'}
        call_info = {'instance_update': 0}

        def fake_instance_update(context, uuid, values):
            call_info['instance_update'] += 1

        self.stubs.Set(db, 'instance_update', fake_instance_update)

        # We have a parent listed in the default cell_get_all
        self.cells_manager.instance_update(fake_context, instance_info,
                routing_path='some_child.me')
        self.assertEqual(call_info['instance_update'], 0)

    def test_instance_update_when_doesnt_exist(self):
        fake_context = 'fake_context'

        instance_info = {'uuid': 'fake_uuid', 'updated_at': 'foo'}
        call_info = {'instance_update': 0, 'instance_create': 0}

        def fake_instance_update(context, uuid, values):
            expected_values = instance_info.copy()
            # Need to make sure the correct cell ended up in here based
            # on the routing path.  Since updates flow up, the cell
            # name is the reverse of the routing path
            expected_values['cell_name'] = 'a.b.c.d.e'
            self.assertEqual(uuid, instance_info['uuid'])
            self.assertEqual(values, expected_values)
            call_info['instance_update'] += 1
            raise exception.InstanceNotFound()

        def fake_instance_create(context, values):
            self.assertEqual(values, instance_info)
            call_info['instance_create'] += 1

        self.stubs.Set(db, 'instance_update', fake_instance_update)
        self.stubs.Set(db, 'instance_create', fake_instance_create)

        # We have a parent listed in the default cell_get_all, so reset
        # this so we'll update
        self.cells_manager.parent_cells = {}
        self.cells_manager.instance_update(fake_context, instance_info,
                routing_path='e.d.c.b.a')
        self.assertEqual(call_info['instance_update'], 1)
        self.assertEqual(call_info['instance_create'], 1)

    def test_instance_destroy(self):
        fake_context = 'fake_context'

        instance_info = {'uuid': 'fake_uuid'}
        call_info = {'instance_destroy': 0}

        def fake_instance_destroy(context, uuid):
            self.assertEqual(uuid, instance_info['uuid'])
            call_info['instance_destroy'] += 1

        self.stubs.Set(db, 'instance_destroy', fake_instance_destroy)

        # We have a parent listed in the default cell_get_all, so reset
        # this so we'll update
        self.cells_manager.parent_cells = {}
        self.cells_manager.instance_destroy(fake_context, instance_info,
                routing_path='some_child.me')
        self.assertEqual(call_info['instance_destroy'], 1)

    def test_instance_destroy_ignored_when_not_at_top(self):
        fake_context = 'fake_context'

        instance_info = {'uuid': 'fake_uuid'}
        call_info = {'instance_destroy': 0}

        def fake_instance_destroy(context, uuid):
            call_info['instance_destroy'] += 1

        self.stubs.Set(db, 'instance_destroy', fake_instance_destroy)

        # We have a parent listed in the default cell_get_all
        self.cells_manager.instance_destroy(fake_context, instance_info)
        self.assertEqual(call_info['instance_destroy'], 0)

    def test_send_raw_message_to_cell_passes_to_driver(self):
        # We can't use self.cells_manager because it has stubbed
        # send_raw_message_to_cell
        mgr = cells_manager.CellsManager(
                cells_driver_cls=fakes.FakeCellsDriver,
                cells_scheduler_cls=fakes.FakeCellsScheduler)

        fake_context = 'fake_context'
        fake_cell = 'fake_cell'
        fake_message = {'method': 'fake_method', 'args': {}}
        call_info = {'send_message': 0}

        def fake_send_message_to_cell(context, cell, message):
            self.assertEqual(context, fake_context)
            self.assertEqual(cell, fake_cell)
            self.assertEqual(message, fake_message)
            call_info['send_message'] += 1

        self.stubs.Set(mgr.driver, 'send_message_to_cell',
                fake_send_message_to_cell)

        mgr.send_raw_message_to_cell(fake_context, fake_cell, fake_message)
        self.assertEqual(call_info['send_message'], 1)

    def test_schedule_calls_get_proxied(self):

        call_info = {'sched_test_method': 0}

        method_kwargs = {'test_arg': 123, 'test_arg2': 456}

        def fake_schedule_test_method(**kwargs):
            self.assertEqual(kwargs, method_kwargs)
            call_info['sched_test_method'] += 1
            pass

        self.stubs.Set(self.cells_manager.scheduler, 'schedule_test_method',
                fake_schedule_test_method)

        self.cells_manager.schedule_test_method(**method_kwargs)
        self.assertEqual(call_info['sched_test_method'], 1)
