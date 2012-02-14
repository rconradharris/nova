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
Common methods for Cells.
"""

from nova import flags
from nova import log as logging

FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.cells.common')


def form_routing_message(dest_cell_name, direction, method,
        method_kwargs, need_response=False, response_uuid=None,
        routing_path=None):
    """Create a routing message."""

    args = {'dest_cell_name': dest_cell_name,
            'routing_path': routing_path,
            'direction': direction,
            'message': {'method': method, 'args': method_kwargs}}
    if need_response:
        args['need_response'] = True
    if response_uuid:
        args['response_uuid'] = response_uuid
    return {'method': 'route_message', 'args': args}


def form_broadcast_message(direction, method, method_kwargs,
        routing_path=None, hopcount=0, fanout=False):
    """Create a broadcast message."""
    args = {'direction': direction,
            'message': {'method': method, 'args': method_kwargs},
            'routing_path': routing_path,
            'hopcount': hopcount,
            'fanout': fanout}
    return {'method': 'broadcast_message', 'args': args}


def form_instance_update_broadcast_message(instance):
    instance = dict(instance.iteritems())
    # Remove things that we can't update in the parent.  'cell_name'
    # is included in this list.. because it'll always be empty in
    # a child zone... and we don't want it to overwrite the column
    # in the parent.
    items_to_remove = ['id', 'security_groups', 'instance_type',
            'volumes', 'cell_name']
    for key in items_to_remove:
        instance.pop(key, None)
    # Fixup info_cache
    info_cache = instance.pop('info_cache', None)
    if info_cache is not None:
        instance['info_cache'] = dict(info_cache.iteritems())
        instance['info_cache'].pop('id', None)
    # Fixup metadata (should be a dict for update, not a list)
    if 'metadata' in instance and isinstance(instance['metadata'], list):
        metadata = dict([(md['key'], md['value'])
                for md in instance['metadata']])
        instance['metadata'] = metadata

    return form_broadcast_message('up', 'instance_update',
            {'instance_info': instance})


def form_instance_destroy_broadcast_message(instance):
    instance_info = {'uuid': instance['uuid']}
    return form_broadcast_message('up', 'instance_destroy',
            {'instance_info': instance_info})


def reverse_path(path):
    """Reverse a path.  Used for sending responses upstream."""
    path_parts = path.split('.')
    path_parts.reverse()
    return '.'.join(path_parts)
