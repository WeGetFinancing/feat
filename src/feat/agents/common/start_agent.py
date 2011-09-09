# F3AT - Flumotion Asynchronous Autonomous Agent Toolkit
# Copyright (C) 2010,2011 Flumotion Services, S.A.
# All rights reserved.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# See "LICENSE.GPL" in the source distribution for more information.

# Headers in this file shall remain intact.
from feat.agents.base import task, replay, agent
from feat.agents.common import raage, host
from feat.common import fiber


class GloballyStartAgent(task.BaseTask):
    '''
    This goal of this task is to start an agent somewhere in a cluser,
    being given only his descriptor. It consists of following steps:

    1. Clear the shard field from the agents descriptor. This step is necessary
       to make the new instance of the agent bind to correct exchange.
    2. Discover Resource Allocation Agent running in the shard.
    3. Ask him for the allocation (retrying protocol with max 3 retries)
    4. Ask resulting host agent to run the agent.
    '''

    timeout = None

    protocol_id = 'start-agent-globally'

    @replay.entry_point
    def initiate(self, state, desc, **kwargs):
        state.descriptor = desc
        state.keywords = kwargs
        state.factory = agent.registry_lookup(state.descriptor.document_type)
        # we are setting shard=None here first, because of the logic in
        # Host Agent which prevents it from changing the shard field if it
        # has been set to sth meaningfull (not in [None, 'lobby'])
        f = state.descriptor.set_shard(state.agent, None)
        f.add_callback(self._store_descriptor)
        f.add_callback(fiber.drop_param, self._retry)
        return f

    @replay.mutable
    def _retry(self, state):
        resc = state.descriptor.extract_resources()
        f = raage.retrying_allocate_resource(
            state.agent, resources=resc,
            categories=state.factory.categories, max_retries=3)
        f.add_callback(self._request_starting_host)
        return f

    @replay.mutable
    def _request_starting_host(self, state, (allocation_id, recp)):
        f = host.start_agent(state.agent, recp, state.descriptor,
                             allocation_id, **state.keywords)
        f.add_errback(self._starting_failed)
        return f

    @replay.immutable
    def _starting_failed(self, state, fail):
        self.error("Starting agent failed with: %r, despite the fact "
                   "that getting allocation was successful. "
                   "I will retry the whole procedure.", fail)
        # TODO: release allocation from the host? not sure if it makes sense
        # as this failure most likely means that that host died in the middle
        return self._retry()

    @replay.mutable
    def _store_descriptor(self, state, desc):
        state.descriptor = desc
