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
Cells Scheduler
"""
import random

from nova import compute
from nova.db import base
from nova import flags
from nova import log as logging
from nova import rpc
from nova.cells import common as cells_common

LOG = logging.getLogger('nova.cells.driver')
FLAGS = flags.FLAGS


class CellsScheduler(base.Base):
    """The cells scheduler."""

    def __init__(self, manager):
        super(CellsScheduler, self).__init__()
        self.manager = manager
        self.compute_api = compute.API()

    def _create_instance_here(self, context, request_spec):
        instance_values = request_spec['instance_properties']
        instance = self.compute_api.create_db_entry_for_new_instance(
                context,
                request_spec['instance_type'],
                request_spec['image'],
                instance_values,
                request_spec['security_group'],
                request_spec['block_device_mapping'])
        bcast_msg = cells_common.form_instance_update_broadcast_message(
                instance)
        self.manager.broadcast_message(context, **bcast_msg['args'])

    def _get_weighted_cells_for_instance(self, context, request_spec,
            filter_properties):
        """Returns a random selection, or self if no child cells"""
        children = self.manager.get_child_cells()
        if not children:
            # No more children... I must be the only choice.
            return [self.manager.my_cell_info]
        random.shuffle(children)
        return children

    def schedule_run_instance(self, context, **kwargs):

        request_spec = kwargs.get('request_spec')
        filter_properties = kwargs.get('filter_properties', {})

        cell_infos = self._get_weighted_cells_for_instance(context,
                request_spec, filter_properties)
        for cell_info in cell_infos:
            try:
                if cell_info.is_me:
                    # Need to create instance DB entry as scheduler
                    # thinks it's already created... At least how things
                    # currently work.
                    self._create_instance_here(context, request_spec)
                    fwd_msg = {'method': 'run_instance', 'args': kwargs}
                    rpc.cast(context, FLAGS.scheduler_topic, fwd_msg)
                else:
                    # Forward request to cell
                    fwd_msg = {'method': 'schedule_run_instance',
                                         'args': kwargs}
                    self.manager.send_raw_message_to_cell(context,
                            cell_info, fwd_msg)
                return
            except Exception:
                LOG.exception(_("Couldn't communicate with cell '%s'") %
                        cell_info.name)
        # FIXME(comstud)
        msg = _("Couldn't communicate with any cells")
        LOG.error(msg)
