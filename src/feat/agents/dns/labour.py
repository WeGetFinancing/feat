from zope.interface import Interface

__all__ = ["IDNSServerPatron", "EqualityMixin",
           "IDNSServerLabourFactory", "IDNSServerLabour"]


class EqualityMixin(object):

    def __eq__(self, other):
        if isinstance(other, type(self)):
            return True
        return NotImplemented

    def __ne__(self, other):
        if isinstance(other, type(self)):
            return False
        return NotImplemented


class IDNSServerPatron(Interface):

    def lookup_address(self, name, address):
        '''Lookups IPs for specified name resolution for client
        with specified address.'''

    def lookup_ns(self, name):
        '''@return: a name server and a TTL.'''


class IDNSServerLabourFactory(Interface):

    def __call__(agent):
        '''
        @returns: L{IManagerLabour}
        '''


class IDNSServerLabour(Interface):

    def initiate():
        '''Initialises the labour.'''

    def startup(port):
        '''Startups the labour, starting to listen
        on specified port for DNS queries.'''

    def cleanup():
        '''Cleanup the labour, stop listening for DNS queries.'''
