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

from feat.common import fiber
from feat.agencies import message
from feat.agents.base import agent, partners, contractor, replay, manager
from feat.agents.common import rpc, start_agent, monitor

from featchat.agents.common import connection
from featchat.application import featchat


@featchat.register_restorator
class ConnectionPartner(agent.BasePartner):
    pass


class Partners(agent.Partners):

    application = featchat

    partners.has_many('connections', 'connection_agent', ConnectionPartner)


@featchat.register_agent('room_agent')
class RoomAgent(agent.BaseAgent):

    restart_strategy = monitor.RestartStrategy.wherever

    partners_class = Partners

    @replay.mutable
    def initiate(self, state):
        state.name = state.medium.get_descriptor().name
        state.medium.register_interest(CreateConnectionContractor)

    @replay.journaled
    def startup(self, state):
        return self.startup_monitoring()

    ### public api ###

    @rpc.publish
    @replay.journaled
    def get_list(self, state):
        if not state.partners.connections:
            return fiber.succeed(dict())

        prot = self.initiate_protocol(
            InspectManager, state.partners.connections)
        return prot.notify_finish()

    @rpc.publish
    @replay.journaled
    def generate_join_url(self, state):
        recipients = state.partners.connections + [self.get_own_address()]
        prot = self.initiate_protocol(JoinManager, recipients)
        return prot.notify_finish()

    ### endof public api

    @replay.journaled
    def create_new_connection(self, state):
        desc = connection.Descriptor(name=state.name)
        f = self.save_document(desc)
        f.add_callback(fiber.inject_param, 1,
                       self.initiate_protocol, start_agent.GloballyStartAgent)
        f.add_callback(fiber.call_param, 'notify_finish')
        f.add_callback(self.establish_partnership)
        return f


class JoinManager(manager.BaseManager):
    '''
    This manager takes decision which connection manager to join. It also
    receives the bid generated by CreateConnectionContractor (running in the
    same agent) which represents creates new ConnectionAgent.
    '''

    protocol_id = 'join-room'

    application = featchat

    @replay.journaled
    def initiate(self, state):
        announce = message.Announcement()
        state.medium.announce(announce)

    @replay.journaled
    def closed(self, state):
        best = message.Bid.pick_best(state.medium.get_bids())
        if best:
            state.medium.grant((best[0], message.Grant(), ))

    @replay.journaled
    def completed(self, state, reports):
        return reports[0].payload


class CreateConnectionContractor(contractor.BaseContractor):
    '''
    This is contractor is taking part in join-room contract at the same
    rights like the connection agents. It generates the bid with the highest
    cost so that it is always the last choice.
    '''
    protocol_id = 'join-room'

    application = featchat

    @replay.journaled
    def announced(self, state, announce):
        # here we put the bid with the high cost, it should aways bid worse
        # than the one generated by existing
        bid = message.Bid(payload=dict(cost=100))
        state.medium.bid(bid)

    @replay.journaled
    def granted(self, state, grant):
        f = state.agent.create_new_connection()
        f.add_callback(state.agent.call_remote, 'generate_join_url')
        f.add_callback(self._finalize)
        return f

    @replay.journaled
    def _finalize(self, state, payload):
        report = message.FinalReport()
        report.payload = payload
        state.medium.finalize(report)


class InspectManager(manager.BaseManager):

    protocol_id = 'inspect-room'

    application = featchat

    @replay.mutable
    def initiate(self, state):
        announce = message.Announcement()
        state.medium.announce(announce)
        state.result = dict()

    @replay.mutable
    def closed(self, state):
        bids = state.medium.get_bids()

        # construct the result combining payloads of the bids received
        for bid in bids:
            state.result.update(bid.payload)

        # now grant bids representing empty connection agent, in case we
        # have more than one
        to_grant = list()
        seen = 0
        for bid in bids:
            if self._is_empty(bid):
                seen += 1
                if seen > 1:
                    to_grant.append(bid)
        if not to_grant:
            state.medium.terminate(state.result)
        else:
            state.medium.grant([(x, message.Grant()) for x in to_grant])

    @replay.journaled
    def expired(self, state):
        return state.medium.terminate(state.result)

    @replay.journaled
    def completed(self, state, reports):
        return state.result

    @replay.journaled
    def aborted(self, state):
        return state.medium.terminate(state.result)

    @replay.journaled
    def cancelled(self, state, cancellation):
        return state.medium.terminate(state.result)

    ### private ###

    def _is_empty(self, bid):
        return len(bid.payload) == 0
