# Copyright 2012 Rackspace Hosting
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
Tests For Scheduler Host Filters.
"""

from nova.compute import vm_states as compute_vm_states
from nova import context
from nova import flags
from nova.scheduler import filters
from nova.tests.scheduler import rackspace_fakes
from nova import test

flags.DECLARE('rackspace_max_instances_per_host',
        'nova.scheduler.filters.rackspace_filter')
flags.DECLARE('rackspace_max_ios_per_host',
        'nova.scheduler.filters.rackspace_filter')


class HostFiltersTestCase(test.TestCase):
    """Test case for host filters."""

    def setUp(self):
        super(HostFiltersTestCase, self).setUp()
        self.flags(rackspace_max_ios_per_host=10,
                rackspace_max_instances_per_host=50)
        self.context = context.RequestContext('fake', 'fake')
        classes = filters.get_filter_classes(
                ['nova.scheduler.filters.standard_filters'])
        self.class_map = {}
        for cls in classes:
            self.class_map[cls.__name__] = cls

    def test_rackspace_filter_num_iops_passes(self):
        filt_cls = self.class_map['RackspaceFilter']()
        vm_states = {compute_vm_states.BUILDING: 2,
                     compute_vm_states.RESIZING: 2,
                     compute_vm_states.REBUILDING: 2}
        host = rackspace_fakes.FakeHostState('host1', 'compute',
                {'vm_states': vm_states})
        self.assertTrue(filt_cls.host_passes(host, {}))

    def test_rackspace_filter_num_iops_fails(self):
        filt_cls = self.class_map['RackspaceFilter']()
        vm_states = {compute_vm_states.BUILDING: 4,
                     compute_vm_states.RESIZING: 5,
                     compute_vm_states.REBUILDING: 2}
        host = rackspace_fakes.FakeHostState('host1', 'compute',
                {'vm_states': vm_states})
        self.assertFalse(filt_cls.host_passes(host, {}))

    def test_rackspace_filter_num_instances_passes(self):
        filt_cls = self.class_map['RackspaceFilter']()
        host = rackspace_fakes.FakeHostState('host1', 'compute',
                {'num_instances': 49})
        self.assertTrue(filt_cls.host_passes(host, {}))

    def test_rackspace_filter_num_instances_fails(self):
        filt_cls = self.class_map['RackspaceFilter']()
        host = rackspace_fakes.FakeHostState('host1', 'compute',
                {'num_instances': 51})
        self.assertFalse(filt_cls.host_passes(host, {}))
