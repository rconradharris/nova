# Copyright (c) 2012 Openstack, LLC.
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
Cells Service Manager
"""

import datetime
import sys
import traceback

from eventlet import queue

from nova import compute
from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import manager
from nova import network
from nova.openstack.common import cfg
from nova.rpc import common as rpc_common
from nova import utils
from nova import volume
from nova.cells import common as cells_common

flag_opts = [
        cfg.StrOpt('cells_driver',
                    default='nova.cells.rpc_driver.CellsRPCDriver',
                    help='Cells driver to use'),
        cfg.StrOpt('cells_scheduler',
                    default='nova.cells.scheduler.CellsScheduler',
                    help='Cells scheduler to use'),
        cfg.IntOpt('cell_db_check_interval',
                    default=60,
                    help='Seconds between getting fresh cell info from db.'),
        cfg.IntOpt('cell_max_broadcast_hop_count',
                    default=10,
                    help='Maximum number of hops for a broadcast message.'),
]


LOG = logging.getLogger('nova.cells.manager')
FLAGS = flags.FLAGS
FLAGS.register_opts(flag_opts)


class CellInfo(object):
    """Holds information ior a particular cell."""
    def __init__(self, cell_name, is_me=False):
        self.name = cell_name
        self.is_me = is_me
        self.last_seen = datetime.datetime.min
        self.capabilities = {}
        self.db_info = {}

    def update_db_info(self, cell_db_info):
        """Update cell credentials from db"""
        self.db_info = dict(
                [(k, v) for k, v in cell_db_info.iteritems()
                        if k != 'name'])

    def update_metadata(self, cell_metadata):
        """Update cell metadata after successful communications with
           child cell."""
        self.last_seen = utils.utcnow()
        self.capabilities = dict(
                [(k, v) for k, v in cell_metadata.iteritems()
                        if k != 'name'])

    def get_cell_info(self):
        db_fields_to_return = ['id', 'is_parent', 'weight_scale',
                'weight_offset', 'username', 'rpc_host', 'rpc_port']
        cell_info = dict(name=self.name, capabilities=self.capabilities)
        if self.db_info:
            for field in db_fields_to_return:
                cell_info[field] = self.db_info[field]
        return cell_info


class CellsManager(manager.Manager):
    """Handles cell communication."""

    def __init__(self, cells_driver_cls=None, cells_scheduler_cls=None,
            cell_info_cls=None, *args, **kwargs):
        super(CellsManager, self).__init__(*args, **kwargs)
        self.api_map = {'compute': compute.API(),
                        'network': network.API(),
                        'volume': volume.API()}
        if not cells_driver_cls:
            cells_driver_cls = utils.import_class(FLAGS.cells_driver)
        if not cells_scheduler_cls:
            cells_scheduler_cls = utils.import_class(FLAGS.cells_scheduler)
        if not cell_info_cls:
            cell_info_cls = CellInfo
        self.driver = cells_driver_cls(self)
        self.scheduler = cells_scheduler_cls(self)
        self.cell_info_cls = cell_info_cls
        self.my_cell_info = cell_info_cls(FLAGS.cell_name, is_me=True)
        my_cell_capabs = dict([cap.split('=', 1)
                for cap in FLAGS.cell_capabilities])
        self.my_cell_info.update_metadata(my_cell_capabs)
        self.response_queues = {}
        self.parent_cells = {}
        self.child_cells = {}
        self.last_cell_db_check = datetime.datetime.min
        self.refresh_cells_from_db(context.get_admin_context())

    def __getattr__(self, key):
        """Makes all scheduler_ methods pass through to scheduler"""
        if key.startswith("schedule_"):
            try:
                return getattr(self.scheduler, key)
            except AttributeError, e:
                with utils.save_and_reraise_exception():
                    LOG.error(_("Cells scheduler has no method '%s'") % key)
        raise AttributeError(_("Cells manager has no attribute '%s'") %
                key)

    def get_cell_info(self, context):
        """Return cell information for all cells."""
        cell_list = [cell.get_cell_info()
                for cell in self.child_cells.itervalues()]
        cell_list.extend([cell.get_cell_info()
                for cell in self.parent_cells.itervalues()])
        return cell_list

    def _cell_get_all(self, context):
        """Get all cells from the DB.  Used to stub in tests."""
        return self.db.cell_get_all(context)

    def _refresh_cells_from_db(self, context):
        """Make our cell info map match the db."""
        # Add/update existing cells ...
        db_cells = self._cell_get_all(context)
        db_cells_dict = dict([(cell['name'], cell) for cell in db_cells])

        # Update current cells.  Delete ones that disappeared
        for cells_dict in (self.parent_cells, self.child_cells):
            for cell_name, cell_info in cells_dict.items():
                is_parent = cell_info.db_info['is_parent']
                db_dict = db_cells_dict.get(cell_name)
                if db_dict and is_parent == db_dict['is_parent']:
                    cell_info.update_db_info(db_dict)
                else:
                    del cells_dict[cell_name]

        # Add new cells
        for cell_name, db_info in db_cells_dict.items():
            if db_info['is_parent']:
                cells_dict = self.parent_cells
            else:
                cells_dict = self.child_cells
            if cell_name not in cells_dict:
                cells_dict[cell_name] = self.cell_info_cls(cell_name)
                cells_dict[cell_name].update_db_info(db_info)

    @manager.periodic_task
    def refresh_cells_from_db(self, context):
        """Update status for all cells.  This should be called
        periodically to refresh the cell states.
        """
        diff = utils.utcnow() - self.last_cell_db_check
        if diff.seconds >= FLAGS.cell_db_check_interval:
            LOG.debug(_("Updating cell cache from db."))
            self.last_cell_db_check = utils.utcnow()
            self._refresh_cells_from_db(context)

    def get_child_cells(self):
        """Return list of child cell_infos."""
        return self.child_cells.values()

    def get_parent_cells(self):
        """Return list of parent cell_infos."""
        return self.parent_cells.values()

    def _process_message_for_me(self, context, message, **kwargs):
        """Process a message for our cell."""
        routing_path = kwargs.get('routing_path')
        method = message['method']
        args = message.get('args', {})
        fn = getattr(self, method)
        return fn(context, routing_path=routing_path, **args)

    def send_raw_message_to_cell(self, context, cell, message):
        self.driver.send_message_to_cell(context, cell, message)

    def _find_next_hop(self, dest_cell_name, routing_path, direction):
        """Return the cell for the next routing hop.  The next hop might
        be ourselves if this is where the message is supposed to go.
        """
        if dest_cell_name == routing_path:
            return self.my_cell_info
        current_hops = routing_path.count('.')
        next_hop_num = current_hops + 1
        dest_hops = dest_cell_name.count('.')
        if dest_hops < current_hops:
            reason = _("destination is %(dest_cell_name)s but routing_path "
                    "is %(routing_path)s") % locals()
            raise exception.CellRoutingInconsistency(reason=reason)
        dest_name_parts = dest_cell_name.split('.')
        if ('.'.join(dest_name_parts[:next_hop_num]) !=
                routing_path):
            reason = _("destination is %(dest_cell_name)s but routing_path "
                    "is %(routing_path)s") % locals()
            raise exception.CellRoutingInconsistency(reason=reason)
        next_hop_name = dest_name_parts[next_hop_num]
        if direction == 'up':
            next_hop = self.parent_cells.get(next_hop_name)
        else:
            next_hop = self.child_cells.get(next_hop_name)
        if not next_hop:
            ztype = 'parent' if direction == 'up' else 'child'
            reason = _("Unknown %(ztype)s at hop %(next_hop_num)s when "
                    "routing to %(dest_cell_name)s") % locals()
            raise exception.CellRoutingInconsistency(reason=reason)
        return next_hop

    def _send_response(self, context, response_uuid, routing_path,
            direction, result, failure=False):
        """Send a response back to the top of the current routing_path."""

        # Reverse the current routing path to figure out where to send
        # the result
        dest_cell = cells_common.reverse_path(routing_path)
        # Routing path for the response starts with us
        resp_routing_path = self.my_cell_info.name
        next_hop = self._find_next_hop(dest_cell, resp_routing_path,
                direction)
        result_info = {'result': result, 'failure': failure}
        if next_hop.is_me:
            # Response was for me!  Just call the method directly.
            self.send_response(context, response_uuid, result_info)
            return
        kwargs = {'response_uuid': response_uuid,
                  'result_info': result_info}
        routing_message = cells_common.form_routing_message(dest_cell,
                direction, 'send_response', kwargs,
                routing_path=resp_routing_path)
        self.send_raw_message_to_cell(context, next_hop, routing_message)

    def send_response(self, context, response_uuid, result_info, **kwargs):
        """This method is called when a another cell has responded to a
        request initiated from this cell.  (The response was encapsulated
        inside a routing message, so this method is only called in the cell
        where the request was initiated.
        """
        # Find the response queue the caller is waiting on
        response_queue = self.response_queues.get(response_uuid)
        # Just drop the response if we don't have a place to put it
        # anymore.  Likely we were restarted..
        if response_queue:
            if result_info.get('failure', False):
                result = rpc_common.RemoteError(*result_info['result'])
            else:
                result = result_info['result']
            response_queue.put(result)

    def route_message(self, context, dest_cell_name, routing_path,
            direction, message, response_uuid=None, need_response=None,
            **kwargs):
        """Route a message to the destination cell."""
        # Append our name to the routing path, or set it to ourselves.
        # No routing path means the message originated from our cell.
        routing_path = ((routing_path and routing_path + '.' or '') +
                self.my_cell_info.name)
        resp_direction = 'up' if direction == 'down' else 'down'
        resp_queue = None

        if need_response:
            # 'need_response' can only be True if the request came from
            # our own cell.  We could verify this by checking that
            # routing_path == our name... but there's no need.
            #
            # Set up a queue for the response so we can wait for a cell
            # to respond.  A cell will callback into 'self.send_response'
            # which will add the entry into this queue when it is
            # received.
            resp_queue = queue.Queue()
            response_uuid = str(utils.gen_uuid())
            self.response_queues[response_uuid] = resp_queue

        try:
            next_hop = self._find_next_hop(dest_cell_name, routing_path,
                    direction)
            if next_hop.is_me:
                kwargs['routing_path'] = routing_path
                result = self._process_message_for_me(context, message,
                        **kwargs)
                if not response_uuid:
                    # No response desired
                    return result
                # If an exception is raised during trying to send the
                # response... note we'll try to send another response below
                # in 'except:' to indicate a failure.  This is probably
                # okay, even though it might raise again.
                self._send_response(context, response_uuid, routing_path,
                    resp_direction, result, failure=False)
            else:
                # Forward the message to the next hop
                routing_message = cells_common.form_routing_message(
                        dest_cell_name, direction, message['method'],
                        message['args'], response_uuid=response_uuid,
                        routing_path=routing_path)
                self.send_raw_message_to_cell(context, next_hop,
                        routing_message)
            # Fall through in case we need to wait for response in the
            # resp_queue
        except Exception, e:
            exc = sys.exc_info()
            result = (exc[0].__name__, str(exc[1]),
                    traceback.format_exception(*exc))
            result = sys.exc_info()
            LOG.exception(_("Received exception during cell routing: "
                    "%(e)s") % locals())
            if response_uuid:
                # Caller wanted a response, so send them an error.
                LOG.debug(_("Sending %(result)s back to %(routing_path)s") %
                        locals())
                self._send_response(context, response_uuid,
                        routing_path, resp_direction, result,
                        failure=True)

        if resp_queue:
            result = resp_queue.get()
            del self.response_queues[response_uuid]
            if isinstance(result, BaseException):
                raise result
            return result
        # Message forwarded and no waiting for response necessary

    def broadcast_message(self, context, direction, message, hopcount,
            fanout, routing_path=None, **kwargs):
        """Broadcast a message to all parent or child cells and also
        process it locally.
        """

        routing_path = ((routing_path and routing_path + '.' or '') +
                self.my_cell_info.name)

        if hopcount > FLAGS.cell_max_broadcast_hop_count:
            max_hops = FLAGS.cell_max_broadcast_hop_count
            detail = _("Broadcast message '%(message)s' reached max hop "
                    "count: %(hopcount)s > %(max_hops)s") % locals()
            LOG.error(detail)
            return

        if direction == 'up':
            cells = self.get_parent_cells()
        else:
            cells = self.get_child_cells()

        hopcount += 1
        bcast_msg = cells_common.form_broadcast_message(direction,
                message['method'], message['args'],
                routing_path=routing_path, hopcount=hopcount, fanout=fanout)
        # Forward request on to other cells
        for cell in cells:
            try:
                self.send_raw_message_to_cell(context, cell, bcast_msg)
            except Exception, e:
                cell_name = cell.name
                LOG.exception(_("Error sending broadcast to cell "
                    "'%(cell_name)s': %(e)s") % locals())
        # Now let's process it.
        kwargs['routing_path'] = routing_path
        self._process_message_for_me(context, message, **kwargs)

    def run_service_api_method(self, context, service_name, method_info,
            routing_path=None, **kwargs):
        """Caller wants us to call a method in a service API"""
        api = self.api_map.get(service_name)
        if not api:
            detail = _("Unknown service API: %s") % service_name
            raise exception.CellServiceAPIMethodNotFound(detail=detail)
        method = method_info['method']
        fn = getattr(api, method, None)
        if not fn:
            detail = _("Unknown method '%(method)s' in %(service_name)s "
                    "API") % locals()
            raise exception.CellServiceAPIMethodNotFound(detail=detail)
        # FIXME(comstud): Make more generic later.  Finish 'volume' and
        # 'network' service code
        args = list(method_info['method_args'])
        if service_name == 'compute':
            # 1st arg is instance_uuid that we need to turn into the
            # instance object.
            instance = db.instance_get_by_uuid(context, args[0])
            args[0] = instance
        return fn(context, *args, **method_info['method_kwargs'])

    def instance_update(self, context, instance_info, routing_path=None,
            **kwargs):
        """Update an instance in the DB if we're a top level cell."""
        if (self.get_parent_cells() or
                routing_path == self.my_cell_info.name):
            # Only update the DB if we're at the very top and the
            # call didn't originate from ourselves
            return
        instance_uuid = instance_info['uuid']
        if routing_path:
            instance_info['cell_name'] = cells_common.reverse_path(
                    routing_path)
        else:
            LOG.error(_("No routing_path for instance_update of "
                    "%(instance_uuid)s") % locals())
        LOG.debug(_("Got update for instance %(instance_uuid)s: "
                "%(instance_info)s") % locals())
        info_cache = instance_info.pop('info_cache', None)
        try:
            self.db.instance_update(context, instance_uuid, instance_info)
        except exception.NotFound:
            # Strange.
            self.db.instance_create(context, instance_info)
        if info_cache:
            self.db.instance_info_cache_update(context, instance_uuid,
                    info_cache)

    def instance_destroy(self, context, instance_info, routing_path=None,
            **kwargs):
        """Destroy an instance from the DB if we're a top level cell."""
        if (self.get_parent_cells() or
                routing_path == self.my_cell_info.name):
            # Only update the DB if we're at the very top and the
            # call didn't originate from ourselves
            return
        instance_uuid = instance_info['uuid']
        LOG.debug(_("Got update to delete instance %(instance_uuid)s") %
                locals())
        try:
            self.db.instance_destroy(context, instance_uuid)
        except exception.InstanceNotFound:
            pass
