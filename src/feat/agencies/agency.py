# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import time
import weakref
import uuid
import copy

from twisted.internet import reactor
from zope.interface import implements

from feat.common import (log, manhole, journal, fiber, serialization, delay,
                         error_handler, text_helper, defer)
from feat.agents.base import recipient, replay, descriptor
from feat.agents.base.agent import registry_lookup
from feat.agencies import common
from feat.interface import agency, agent, protocols
from feat.common.serialization import pytree, Serializable

from interface import IListener, IAgencyInitiatorFactory,\
                      IAgencyInterestedFactory, IConnectionFactory

from feat.agencies import contracts, requests, dependency


class AgencyJournalSideEffect(object):

    implements(journal.IJournalSideEffect)

    ### IJournalSideEffect ###

    def __init__(self, serializer, record, function_id, *args, **kwargs):
        self._serializer = serializer
        self._record = record
        self._fun_id = function_id
        self._args = serializer.convert(args or None)
        self._kwargs = serializer.convert(kwargs or None)
        self._effects = []
        self._result = None

    ### IJournalSideEffect Methods ###

    def add_effect(self, effect_id, *args, **kwargs):
        assert self._record is not None
        data = (effect_id,
                self._serializer.convert(args),
                self._serializer.convert(kwargs))
        self._effects.append(data)

    def set_result(self, result):
        assert self._record is not None
        self._result = self._serializer.convert(result)
        return self

    def commit(self):
        assert self._record is not None
        data = (self._fun_id, self._args, self._kwargs,
                self._effects, self._result)
        self._record.extend(data)
        self._record = None
        return self


class AgencyJournalEntry(object):

    implements(journal.IJournalEntry)

    def __init__(self, serializer, record, agent_id, journal_id,
                 function_id, *args, **kwargs):
        self._serializer = serializer
        self._record = record
        self._agent_id = agent_id
        self._journal_id = journal_id
        self._function_id = function_id
        self._args = serializer.convert(args or None)
        self._kwargs = serializer.convert(kwargs or None)
        self._fiber_id = None
        self._fiber_depth = None
        self._result = None
        self._side_effects = []

    ### IJournalEntry Methods ###

    def set_fiber_context(self, fiber_id, fiber_depth):
        assert self._record is not None
        self._fiber_id = fiber_id
        self._fiber_depth = fiber_depth
        return self

    def set_result(self, result):
        assert self._record is not None
        self._result = self._serializer.freeze(result)
        return self

    def new_side_effect(self, function_id, *args, **kwargs):
        assert self._record is not None
        record = []
        self._side_effects.append(record)
        return AgencyJournalSideEffect(self._serializer, record,
                                       function_id, *args, **kwargs)

    def commit(self):
        data = (self._agent_id, self._journal_id, self._function_id,
                self._fiber_id, self._fiber_depth,
                self._args, self._kwargs, self._side_effects, self._result)
        self._record.extend(data)
        self._record = None
        return self


class Agency(manhole.Manhole, log.FluLogKeeper, log.Logger,
             dependency.AgencyDependencyMixin):

    log_category = 'agency'

    __metaclass__ = type('MetaAgency', (type(manhole.Manhole),
                                        type(log.FluLogKeeper)), {})

    implements(agency.IAgency, serialization.IExternalizer)

    _error_handler = error_handler

    def __init__(self):
        log.FluLogKeeper.__init__(self)
        log.Logger.__init__(self, self)
        dependency.AgencyDependencyMixin.__init__(self, agency.ExecMode.test)

        self._agents = []

        self._journal_entries = list()
        self.serializer = pytree.Serializer(externalizer=self)
        self.registry = weakref.WeakValueDictionary()
        self._database = None
        self._messaging = None

    def initiate(self, messaging, database):
        '''
        Asynchronous part of agency initialization. Needs to be called before
        agency is used for anything.
        '''
        self._database = IConnectionFactory(database)
        self._messaging = IConnectionFactory(messaging)
        return defer.succeed(None)

    @manhole.expose()
    def start_agent(self, descriptor, *args, **kwargs):
        factory = agent.IAgentFactory(
            registry_lookup(descriptor.document_type))
        self.log('I will start: %r agent. Args: %r, Kwargs: %r.',
                 factory, args, kwargs)
        medium = AgencyAgent(self, factory, descriptor)
        self._agents.append(medium)

        d = defer.maybeDeferred(medium.initiate)
        #FIXME: we shouldn't need maybe_fiber
        d.addCallback(fiber.drop_result, fiber.maybe_fiber,
                      medium.agent.initiate, *args, **kwargs)
        d.addCallback(fiber.override_result, medium)
        return d

    @manhole.expose()
    def find_agent(self, desc):
        agent_id = (isinstance(desc, descriptor.Descriptor) and desc.doc_id
                    or desc)
        self.log("I'm trying to find the agent with id: %s", agent_id)
        try:
            return next(x for x in self._agents \
                        if x._descriptor.doc_id == agent_id)
        except StopIteration:
            return None

    def shutdown(self):
        '''Called when the agency is ordered to shutdown all the agents..'''
        d = defer.DeferredList([x._terminate() for x in self._agents])
        d.addCallback(lambda _: self._messaging.disconnect())
        return d

    def on_killed(self):
        '''Called when the agency process is terminating. (SIGTERM)'''
        d = defer.DeferredList([x.on_killed() for x in self._agents])
        d.addCallback(lambda _: self._messaging.disconnect())
        return d

    def unregister_agent(self, medium, agent_id):
        self._agents.remove(medium)
        self.journal_agent_deleted(agent_id)

    def get_time(self):
        return time.time()

    # journal specific stuff

    def journal_new_entry(self, agent_id, journal_id,
                          function_id, *args, **kwargs):
        record = []
        self._journal_entries.append(record)
        return AgencyJournalEntry(self.serializer, record, agent_id,
                                  journal_id, function_id, *args, **kwargs)

    def journal_agency_entry(self, agent_id, function_id, *args, **kwargs):
        if journal.add_effect(function_id, *args, **kwargs):
            return

        section = fiber.WovenSection()
        section.enter()

        try:

            desc = section.descriptor
            entry = self.journal_new_entry(agent_id, 'agency',
                                           function_id, *args, **kwargs)
            entry.set_fiber_context(desc.fiber_id, desc.fiber_depth)
            entry.set_result(None)
            entry.commit()

        finally:

            section.abort()

    def journal_protocol_created(self, agent_id, protocol_factory,
                                 medium, *args, **kwargs):
        self.journal_agency_entry(agent_id, 'protocol_created',
                                  protocol_factory, medium, *args, **kwargs)

    def journal_protocol_deleted(self, agent_id, protocol_instance, dummy_id):
        self.journal_agency_entry(agent_id, 'protocol_deleted',
                                  protocol_instance.journal_id, dummy_id)

    def journal_agent_created(self, agent_id, agent_factory, dummy_id):
        self.journal_agency_entry(agent_id, 'agent_created',
                                  agent_factory, dummy_id)

    def journal_agent_deleted(self, agent_id):
        self.journal_agency_entry(agent_id, 'agent_deleted')

    def journal_agent_snapshot(self, agent_id, snapshot):
        self.journal_agency_entry(agent_id, 'snapshot', snapshot)

    # registry

    def register(self, recorder):
        j_id = recorder.journal_id
        self.log('Registering recorder: %r, id: %r',
                 recorder.__class__.__name__, j_id)
        assert j_id not in self.registry
        self.registry[j_id] = recorder

    # IExternalizer

    def identify(self, instance):
        if (journal.IRecorder.providedBy(instance) and
            instance.journal_id in self.registry):
            return instance.journal_id

    def lookup(self, _):
        raise RuntimeError("OOPS, this should never be called "
                           "in production code!!")

    # Snapshot the agents

    @manhole.expose()
    def snapshot_agents(self):
        # reset the registry, so that snapshot contains
        # full objects not just the references
        self.registry = weakref.WeakValueDictionary()
        for agent in self._agents:
            agent.journal_snapshot()

    # Methods exposed for introspection

    @manhole.expose()
    def list_agents(self):
        '''list_agents() -> List agents hosted by the agency.'''

        t = text_helper.Table(fields=("Agent ID", "Agent class", ),
                              lengths=(40, 25, ))

        return t.render((a._descriptor.doc_id, a.log_name, )\
                        for a in self._agents)

    @manhole.expose()
    def get_nth_agent(self, n):
        '''get_nth_agent(n) -> Get the agent by his index in the list.'''

        return self._agents[n]

    @manhole.expose()
    def get_agents(self):
        '''get_agents() -> Get the list of agents hosted by this agency.'''

        return self._agents


class AgencyAgent(log.LogProxy, log.Logger, manhole.Manhole,
                  dependency.AgencyAgentDependencyMixin):
    implements(agent.IAgencyAgent, journal.IRecorderNode,
               journal.IJournalKeeper, serialization.ISerializable)

    log_category = "agency-agent"
    journal_parent = None
    type_name = "agent-medium" # this is used by ISerializable

    def __init__(self, aagency, factory, descriptor):
        log.LogProxy.__init__(self, aagency)
        log.Logger.__init__(self, self)

        self.journal_keeper = self

        self.agency = agency.IAgency(aagency)
        self._descriptor = descriptor
        self.agency.journal_agent_created(descriptor.doc_id, factory,
                                          self.snapshot())
        self.agent = factory(self)
        self.log_name = self.agent.__class__.__name__
        self.log('Instantiated the %r instance', self.agent)

        # instance_id -> IListener
        self._listeners = {}
        # protocol_type -> protocol_id -> protocols.IInterest
        self._interests = {}
        # retrying protocols
        self._retrying_protocols = list()

        self._messaging = None
        self._database = None

        self._updating = False
        self._update_queue = []
        # terminating flag (meant not to run termination procedure more than
        # once)
        self._terminating = False

    def initiate(self):
        '''Establishes the connections to database and messaging platform,
        taking into account that it might meen performing asynchronous job.'''

        def setter(value, name):
            setattr(self, name, value)

        d = defer.maybeDeferred(self.agency._messaging.get_connection, self)
        d.addCallback(setter, '_messaging')
        d.addCallback(lambda _: self.agency._database.get_connection(self))
        d.addCallback(setter, '_database')
        d.addCallback(lambda _: self.join_shard(self._descriptor.shard))
        return d

    def snapshot_agent(self):
        '''Gives snapshot of everything related to the agent'''
        listeners = [i.get_agent_side() for i in self._listeners.values()]
        return (self.agent, listeners, )

    def journal_snapshot(self):
        self.agency.journal_agent_snapshot(self._descriptor.doc_id,
                                           self.snapshot_agent())

    @replay.named_side_effect('AgencyAgent.get_descriptor')
    def get_descriptor(self):
        return copy.deepcopy(self._descriptor)

    def update_descriptor(self, function, *args, **kwargs):
        d = defer.Deferred()
        self._update_queue.append((d, function, args, kwargs))
        self._next_update()
        return d

    def _next_update(self):

        def saved(desc, result, d):
            self.log("Updating descriptor: %r", desc)
            self._descriptor = desc
            d.callback(result)

        def error(failure, d):
            self.error("Failed updating descriptor: %s",
                       failure.getErrorMessage())
            d.errback(failure)

        def next_update(any=None):
            self._updating = False
            reactor.callLater(0, self._next_update)
            return any

        if self._updating:
            # Currently updating descriptor
            return

        if not self._update_queue:
            # No more pending updates
            return

        d, fun, args, kwargs = self._update_queue.pop(0)
        self._updating = True
        try:
            desc = self.get_descriptor()
            result = fun(desc, *args, **kwargs)
            assert not isinstance(result, (defer.Deferred, fiber.Fiber))
            save_d = self.save_document(desc)
            save_d.addCallbacks(callback=saved, callbackArgs=(result, d),
                                errback=error, errbackArgs=(d, ))
            save_d.addBoth(next_update)
        except:
            d.errback()
            next_update()

    @serialization.freeze_tag('AgencyAgent.join_shard')
    def join_shard(self, shard):
        self.log("Join shard called. Shard: %r", shard)
        # Rebind agents queue
        binding = self.create_binding(self._descriptor.doc_id, shard)
        # Iterate over interest and create bindings
        bindings = [x.bind(shard) for x in self._iter_interests()]
        # Remove None elements (private interests)
        bindings = [x for x in bindings if x]
        bindings = [binding] + bindings

        return defer.DeferredList([x.created for x in bindings])

    @serialization.freeze_tag('AgencyAgent.leave_shard')
    def leave_shard(self, shard):
        bindings = self._messaging.get_bindings(shard)
        return defer.DeferredList([x.revoke() for x in bindings])

    @serialization.freeze_tag('AgencyAgent.start_agent')
    def start_agent(self, desc, *args, **kwargs):
        return self.agency.start_agent(desc, *args, **kwargs)

    def on_message(self, message):
        self.log('Received message: %r', message)

        # check if it isn't expired message
        ctime = self.get_time()
        if message.expiration_time < ctime:
            self.log('Throwing away expired message.')
            return False

        # handle registered dialog
        if message.receiver_id is not None and\
           message.receiver_id in self._listeners:
            listener = self._listeners[message.receiver_id]
            listener.on_message(message)
            return True

        # handle new conversation comming in (interest)
        p_type = message.protocol_type
        p_id = message.protocol_id
        if p_type in self._interests and p_id in self._interests[p_type] and\
          isinstance(message, self._interests[p_type][p_id].factory.initiator):
            self.log('Looking for interest to instantiate.')
            factory = self._interests[message.protocol_type]\
                                     [message.protocol_id].factory
            medium_factory = IAgencyInterestedFactory(factory)
            medium = medium_factory(self, message)
            self.agency.journal_protocol_created(self._descriptor.doc_id,
                                                 factory, medium)
            interested = factory(self.agent, medium)
            medium.initiate(interested)
            listener = self.register_listener(medium)
            listener.on_message(message)
            return True

        self.warning("Couldn't find appropriate listener for message: "
                     "%s.%s.%s", message.protocol_type, message.protocol_id,
                     message.__class__.__name__)
        return False

    @serialization.freeze_tag('AgencyAgent.initiate_protocol')
    @replay.named_side_effect('AgencyAgent.initiate_protocol')
    def initiate_protocol(self, factory, recipients, *args, **kwargs):
        self.log('Initiating protocol for factory: %r, args: %r, kwargs: %r',
                 factory, args, kwargs)
        factory = protocols.IInitiatorFactory(factory)
        recipients = recipient.IRecipients(recipients)
        medium_factory = IAgencyInitiatorFactory(factory)
        medium = medium_factory(self, recipients, *args, **kwargs)

        self.agency.journal_protocol_created(
            self._descriptor.doc_id, factory, medium, *args, **kwargs)
        initiator = factory(self.agent, medium)
        self.register_listener(medium)
        medium.initiate(initiator)
        return initiator

    @serialization.freeze_tag('AgencyAgent.retrying_protocol')
    @replay.named_side_effect('AgencyAgent.retrying_protocol')
    def retrying_protocol(self, factory, recipients, max_retries=None,
                          initial_delay=1, max_delay=None,
                          args=None, kwargs=None):

        args = args or tuple()
        kwargs = kwargs or dict()
        r = RetryingProtocol(self, factory, recipients, args, kwargs,
                             max_retries, initial_delay)
        self._retrying_protocols.append(r)
        r.notify_finish().addBoth(
            lambda _: self._retrying_protocols.remove(r))
        return r

    @replay.named_side_effect('AgencyAgent.register_interest')
    def register_interest(self, factory):
        factory = protocols.IInterest(factory)
        p_type = factory.protocol_type
        p_id = factory.protocol_id
        if p_type not in self._interests:
            self._interests[p_type] = dict()
        if p_id in self._interests[p_type]:
            self.error('Already interested in %s.%s protocol!', p_type, p_id)
            return False
        i = Interest(self, factory)
        self._interests[p_type][p_id] = i
        self.debug('Registered interest in %s.%s protocol.', p_type, p_id)
        return i

    @replay.named_side_effect('AgencyAgent.revoke_interest')
    def revoke_interest(self, factory):
        factory = protocols.IInterest(factory)
        p_type = factory.protocol_type
        p_id = factory.protocol_id
        if p_type not in self._interests or\
           p_id not in self._interests[p_type]:
            self.error('Requested to revoke interest we are not interested in!'
                      ' %s.%s', p_type, p_id)
            return False
        self._interests[p_type][p_id].revoke()
        del(self._interests[p_type][p_id])

        return True

    def register_listener(self, listener):
        listener = IListener(listener)
        session_id = listener.get_session_id()
        self.debug('Registering listener session_id: %r', session_id)
        assert session_id not in self._listeners
        self._listeners[session_id] = listener
        return listener

    def unregister_listener(self, session_id):
        if session_id in self._listeners:
            self.debug('Unregistering listener session_id: %r', session_id)
            listener = self._listeners[session_id]
            self.agency.journal_protocol_deleted(
                self._descriptor.doc_id, listener.get_agent_side(),
                listener.snapshot())
            del(self._listeners[session_id])
        else:
            self.error('Tried to unregister listener with session_id: %r, '
                        'but not found!', session_id)

    @replay.named_side_effect('AgencyAgent.get_time')
    def get_time(self):
        return self.agency.get_time()

    def send_msg(self, recipients, msg, handover=False):
        recipients = recipient.IRecipients(recipients)
        if not handover:
            msg.reply_to = recipient.IRecipient(self)
            msg.message_id = str(uuid.uuid1())
        assert msg.expiration_time is not None
        for recp in recipients:
            self.log('Sending message to %r', recp)
            self._messaging.publish(recp.key, recp.shard, msg)
        return msg

    def create_binding(self, key, shard=None):
        return self._messaging.personal_binding(key, shard)

    # Delegation of methods to IDatabaseClient

    @serialization.freeze_tag('AgencyAgency.save_document')
    def save_document(self, document):
        return self._database.save_document(document)

    @serialization.freeze_tag('AgencyAgency.reload_document')
    def reload_document(self, document):
        return self._database.reload_document(document)

    @serialization.freeze_tag('AgencyAgency.delete_document')
    def delete_document(self, document):
        return self._database.delete_document(document)

    @serialization.freeze_tag('AgencyAgency.get_document')
    def get_document(self, document_id):
        return self._database.get_document(document_id)

    def _terminate_procedure(self, body):
        self.log("in _terminate_procedure()")
        assert callable(body)
        if self._terminating:
            # already doing the stuff
            return
        self._terminating = True
        # revoke all interests
        [self.revoke_interest(x.factory) for x in self._iter_interests()]

        # kill all retrying protocols
        d = defer.DeferredList([x.give_up() for x in self._retrying_protocols])
        # kill all listeners
        d.addBoth(self._kill_all_listeners)
        # Run code specific to the given shutdown
        d.addBoth(lambda _: body())
        # tell the agency we are no more
        d.addBoth(lambda doc: self.agency.unregister_agent(self, doc.doc_id))
        # close the messaging connection
        d.addBoth(lambda _: self._messaging.disconnect())
        return d

    def _terminate(self):
        '''terminate() -> Shutdown agent gently removing the descriptor and
        notifying partners.'''

        def generate_body():
            d = defer.succeed(None)
            # run IAgent.shutdown() and wait for
            # the listeners to finish the job
            d.addBoth(self._run_and_wait, self.agent.shutdown)
            # delete the descriptor
            d.addBoth(lambda _: self.delete_document(self._descriptor))
            # TODO: delete the queue
            return d

        return self._terminate_procedure(generate_body)

    @manhole.expose()
    @serialization.freeze_tag('AgencyAgency.terminate')
    def terminate(self):
        reactor.callLater(0, self._terminate)

    def on_killed(self):
        '''called as part of SIGTERM handler.'''

        def generate_body():
            d = defer.succeed(None)
            # run IAgent.killed() and wait for the listeners to finish the job
            d.addBoth(self._run_and_wait, self.agent.killed)
            return d

        return self._terminate_procedure(generate_body)

    def _run_and_wait(self, _, method, *args, **kwargs):
        '''
        Run a agent-side method and wait for all the listeners
        to finish processing.
        '''
        d = fiber.maybe_fiber(method, *args, **kwargs)
        d.addBoth(self.wait_for_listeners_finish)
        return d

    def wait_for_listeners_finish(self):

        def wait_for_listener(listener):
            d = listener.notify_finish()
            d.addErrback(self._ignore_initiator_failed)
            return d

        d = defer.DeferredList(
            [wait_for_listener(x) for x in self._listeners.values()])
        return d

    def _iter_interests(self):
        for p_type in self._interests:
            for x in self._interests[p_type].values():
                yield x

    def _kill_all_listeners(self, *_):

        def expire_one(listener):
            d = listener.expire_now()
            d.addErrback(self._ignore_initiator_failed)
            return d

        d = defer.DeferredList(
            [expire_one(x) for x in self._listeners.values()])
        return d

    def _ignore_initiator_failed(self, fail):
        if fail.check(protocols.InitiatorFailed):
            self.log('Swallowing %r expection.', fail.value)
            return None
        else:
            self.log('Reraising exception %r', fail)
            fail.raiseException()

    ### IRecorderNode Methods ###

    def generate_identifier(self, recorder):
        assert not getattr(self, 'indentifier_generated', False)
        self._identifier_generated = True
        return (self._descriptor.doc_id, )

    ### IJournalKeeper Methods ###

    def register(self, recorder):
        self.agency.register(recorder)

    def new_entry(self, journal_id, function_id, *args, **kwargs):
        return self.agency.journal_new_entry(self._descriptor.doc_id,
                                             journal_id, function_id,
                                             *args, **kwargs)

    ### ISerializable Methods ###

    def snapshot(self):
        return self._descriptor.doc_id

    # For manhole purpose:

    @manhole.expose()
    def get_agent(self):
        '''get_agent() -> Returns the agent side instance.'''
        return self.agent

    @manhole.expose()
    def list_partners(self):
        t = text_helper.Table(fields=["Partner", "Id", "Shard", "Role"],
                  lengths = [20, 35, 35, 10])

        partners = self.agent.query_partners('all')
        return t.render(
            (type(p).__name__, p.recipient.key, p.recipient.shard, p.role, )\
            for p in partners)

    @manhole.expose()
    def list_resource(self):
        t = text_helper.Table(fields=["Name", "Totals", "Allocated"],
                  lengths = [20, 20, 20])
        totals, allocated = self.agent.list_resource()

        def iter(totals, allocated):
            for x in totals:
                yield x, totals[x], allocated[x]

        return t.render(iter(totals, allocated))


@serialization.register
class Interest(Serializable):
    '''Represents the interest from the point of view of agency.
    Manages the binding and stores factory reference'''

    type_name = 'agency-interest'

    factory = None
    binding = None

    def __init__(self, medium, factory):
        self.factory = factory
        self.medium = medium
        self._lobby_binding = None

        self.bind()

    def bind(self, shard=None):
        if self.factory.interest_type == protocols.InterestType.public:
            self.binding = self.medium.create_binding(
                self.factory.protocol_id, shard)
            return self.binding

    @replay.named_side_effect('Interest.revoke')
    def revoke(self):
        if self.factory.interest_type == protocols.InterestType.public:
            self.binding.revoke()

    @replay.named_side_effect('Interest.bind_to_lobby')
    def bind_to_lobby(self):
        assert self._lobby_binding is None
        self._lobby_binding = self.medium._messaging.personal_binding(
            self.factory.protocol_id, 'lobby')

    @replay.named_side_effect('Interest.unbind_from_lobby')
    def unbind_from_lobby(self):
        self._lobby_binding.revoke()
        self._lobby_binding = None

    # ISerializable

    def snapshot(self):
        return dict(factory=self.factory)

    def __eq__(self, other):
        return self.factory == other.factory

    def __ne__(self, other):
        return not self.__eq__(other)


class RetryingProtocol(common.InitiatorMediumBase, log.Logger):

    implements(serialization.ISerializable)

    log_category="retrying-protocol"
    type_name="retrying-protocol"

    def __init__(self, medium, factory, recipients, args, kwargs,
                 max_retries=None, initial_delay=1, max_delay=None):
        common.InitiatorMediumBase.__init__(self)
        log.Logger.__init__(self, medium)

        self.medium = medium
        self.factory = factory
        self.recipients = recipients
        self.args = args
        self.kwargs = kwargs

        self.max_retries = max_retries
        self.max_delay = max_delay
        self.attempt = 0
        self.delay = initial_delay

        self._delayed_call = None
        self._initiator = None

        self._bind()

    # public interface

    @serialization.freeze_tag('RetryingProtocol.notify_finish')
    def notify_finish(self):
        return common.InitiatorMediumBase.notify_finish(self)

    @serialization.freeze_tag('RetryingProtocol.give_up')
    def give_up(self):
        self.max_retries = self.attempt - 1
        if self._delayed_call and not self._delayed_call.called:
            self._delayed_call.cancel()
            return defer.succeed(None)
        if self._initiator:
            d = self._initiator._get_state().medium.expire_now()
            d.addErrback(self.medium._ignore_initiator_failed)
            return d

    # private section

    def _bind(self):
        d = self._fire()
        d.addCallbacks(self._finalize, self._wait_and_retry)

    def _fire(self):
        self.attempt += 1
        self._initiator = self.medium.initiate_protocol(
            self.factory, self.recipients, *self.args, **self.kwargs)
        d = self._initiator.notify_finish()
        return d

    def _finalize(self, result):
        common.InitiatorMediumBase._terminate(self, result)

    def _wait_and_retry(self, failure):
        self.info('Retrying protocol for factory: %r failed for the %d time. ',
                  self.factory, self.attempt)

        self._initiator = None

        # check if we are done
        if self.max_retries is not None and self.attempt > self.max_retries:
            self.info("Will not try to restart.")
            common.InitiatorMediumBase._terminate(self, failure)
            return

        # do retry
        self.info('Will retry in %d seconds', self.delay)
        self._delayed_call = delay.callLater(self.delay, self._bind)

        # adjust the delay
        if self.max_delay is None:
            self.delay *= 2
        elif self.delay < self.max_delay:
            self.delay = min((2 * self.delay, self.max_delay, ))

    # ISerializable

    def snapshot(self):
        return id(self)
