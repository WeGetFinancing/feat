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
from twisted.python.failure import Failure
from twisted.names import dns
from zope.interface import implements, classProvides

from feat.common import serialization, adapter, error
from feat.common.serialization import base

from feat.interface.serialization import IRestorator, ISerializable


class AdaptedMarker(object):
    pass


class BaseAdapter(object):

    adapter_mixin = None

    _adapters = {} # {EXCEPTION_TYPE: ADAPTER_TYPE}

    @classmethod
    def get_adapter(cls, base_type):
        adapter = cls._adapters.get(base_type)
        if adapter is None:
            adapter_name = base_type.__name__ + "Adapter"
            bases = (base_type, AdaptedMarker)
            if cls.adapter_mixin is not None:
                bases += (cls.adapter_mixin, )
            adapter = type(adapter_name, bases, {})
            cls._adapters[base_type] = adapter
        return adapter

    @classmethod
    def get_type(cls, value):
        vtype = type(value)
        if issubclass(vtype, AdaptedMarker):
            return vtype.__bases__[0]
        return vtype


class AdaptedExceptionMixin(object):

    def __eq__(self, other):
        if not isinstance(self, type(other)):
            return NotImplemented
        return (self.args == other.args
                and self.__dict__ == other.__dict__)

    def __ne__(self, other):
        eq = self.__eq__(other)
        return not eq if eq is not NotImplemented else eq


@adapter.register(Exception, ISerializable)
@serialization.register
class ExceptionAdapter(BaseAdapter):

    classProvides(IRestorator)
    implements(ISerializable)

    type_name = "exception"
    adapter_mixin = AdaptedExceptionMixin

    def __init__(self, exception):
        self._args = exception.args
        self._attrs = exception.__dict__
        self._type = self.get_type(exception)

    ### ISerializable Methods ###

    def snapshot(self):
        return self._type, self._args, self._attrs

    @classmethod
    def prepare(self):
        return None

    @classmethod
    def restore(cls, snapshot):
        extype, args, attrs = snapshot
        adapter = cls.get_adapter(extype)
        if issubclass(adapter, UnicodeError):
            # We need to unserialize the UnicodeEncodeError and
            # UnicodeDecodeError
            # in a special way. There is a bug in python:
            # http://bugs.python.org/issue21134
            # Which causes a seg fault later on, when the __str__() is
            # called on the exception instance.
            args = list(args)
            args[0] = str(args[0])
            args[4] = str(args[4])
            ex = adapter(*args)
        else:
            ex = adapter.__new__(adapter)
            ex.args = args
            ex.__dict__.update(attrs)
        return ex


@adapter.register(error.FeatError, ISerializable)
@serialization.register
class FeatErrorAdapter(ExceptionAdapter):
    """I'm cleaning up information about the traceback as we don't want it
    to end up in journal."""

    classProvides(IRestorator)

    def __init__(self, exception):
        ExceptionAdapter.__init__(self, exception)
        if self._attrs.get('cause_traceback'):
            self._attrs['cause_traceback'] = (
                "Traceback information was cleanup up by FeatErrorAdapter")


@adapter.register(Failure, ISerializable)
@serialization.register
class FailureAdapter(Failure, BaseAdapter, base.Serializable):

    type_name = "failure"

    def __init__(self, failure):
        self.__dict__.update(failure.__dict__)
        self.cleanFailure()

    def snapshot(self):
        snapshot = base.Serializable.snapshot(self)
        snapshot['tb'] = None
        snapshot['frames'] = []
        snapshot['stack'] = []
        return snapshot

    def trap(self, *errorTypes):
        error = self.check(*errorTypes)
        if not error:
            self.raiseException()
        return error

    def __eq__(self, other):
        if not isinstance(other, Failure):
            return NotImplemented
        return (self.value == other.value
                and self.type == self.type)

    def __ne__(self, other):
        eq = self.__eq__(other)
        return not eq if eq is not NotImplemented else eq


@adapter.register(dns.Message, ISerializable)
@serialization.register
class MessageAdapter(BaseAdapter, base.Serializable):

    classProvides(IRestorator)
    implements(ISerializable)

    def __init__(self, msg):
        self._msg = msg

    def snapshot(self):
        return self._msg.toStr()

    @classmethod
    def restore(cls, snapshot):
        result = dns.Message()
        result.fromStr(snapshot)
        return result
